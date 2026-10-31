import { useEffect, useState } from 'react';
import { enhanceImage, fetchImageBlobUrl, getImageJob, imageEnhancementInfo, stopImage } from '../lib/sidecar';
import type { ImageJob } from '../lib/sidecar';
import { remember, remembered } from '../lib/awake';
import SaveActions from './SaveActions';

/** Pixel enhancement is separate from generation. Closing the viewer leaves
 * the queued job running; reopening it resumes progress instead of restarting. */
export default function ImageEnhancer({ sourcePath, onView }: {
  sourcePath: string;
  onView: (view: { src: string; name: string } | null) => void;
}) {
  const [info, setInfo] = useState<{ ready: boolean } | null>(null);
  const [job, setJob] = useState<ImageJob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [viewingEnhanced, setViewingEnhanced] = useState(false);
  const key = `uncloud.image.enhancement:${sourcePath}`;
  const jobId = job?.id;

  useEffect(() => {
    let dead = false;
    imageEnhancementInfo().then(value => { if (!dead) setInfo(value); })
      .catch(e => { if (!dead) setError(String(e)); });
    const id = remembered(key)[0];
    if (id) getImageJob(id).then(value => { if (!dead) setJob(value); }).catch(() => undefined);
    return () => { dead = true; };
  }, [key]);

  useEffect(() => {
    if (!jobId) return;
    let dead = false, made: string | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await getImageJob(jobId);
        if (dead) return;
        setJob(next);
        if (next.status === 'done') {
          made = await fetchImageBlobUrl(next.id);
          if (dead) { URL.revokeObjectURL(made); made = null; return; }
          setUrl(made);
          return;
        }
        if (next.done) return;
      } catch (e) { if (!dead) setError(String(e)); }
      if (!dead) timer = setTimeout(() => { void poll(); }, 800);
    };
    void poll();
    return () => { dead = true; clearTimeout(timer); if (made) URL.revokeObjectURL(made); };
  }, [jobId]);

  function show(enhanced: boolean) {
    setViewingEnhanced(enhanced);
    onView(enhanced && url ? { src: url, name: job?.output_path?.split(/[\\/]/).pop() ?? 'enhanced-2x.png' } : null);
  }

  async function start() {
    if (!info) return;
    setStarting(true); setError('');
    try {
      const next = await enhanceImage(sourcePath, !info.ready);
      show(false); setUrl(null); setJob(next); remember(key, [next.id]);
    } catch (e) { setError(String(e)); }
    finally { setStarting(false); }
  }

  const running = !!job && !job.done;
  return <div className="image-enhancement-panel">
    <div className="flex flex-wrap items-center gap-2">
      {url ? <>
        <button className="image-enhancement-button" aria-pressed={!viewingEnhanced} onClick={() => show(false)}>Original</button>
        <button className="image-enhancement-button" aria-pressed={viewingEnhanced} onClick={() => show(true)}>Enhanced 2×</button>
      </> : running ? <>
        <span role="status" className="text-xs">{job.phase}{job.total_steps > 0 ? ` · ${job.step}/${job.total_steps}` : ''}
          {job.elapsed_seconds != null ? ` · ${Math.round(job.elapsed_seconds)}s` : ''}</span>
        <button className="image-enhancement-button" onClick={() => void stopImage(job.id).catch(e => setError(String(e)))}>Stop enhancement</button>
      </> : <button className="image-enhancement-button" disabled={!info || starting} onClick={() => void start()}>
        {starting ? 'Starting…' : info && !info.ready ? 'Download 64 MB & enhance 2×' : 'Enhance 2×'}
      </button>}
      <span className="text-xs text-[var(--text-faint)]">{url ? `Original preserved · ${Math.round(job?.elapsed_seconds ?? 0)}s` : 'Save a larger, sharper copy. Original preserved.'}</span>
    </div>
    {url && <div className="image-enhancement-save"><SaveActions path={job?.output_path ?? null} onDiscarded={() => {
      show(false); setUrl(null); setJob(null); remember(key, []);
    }} /></div>}
    {error || job?.error ? <p role="alert" className="text-xs mt-1">{error || job?.error}</p> : null}
    {job?.status === 'cancelled' && <p className="text-xs">Enhancement stopped. Original preserved.</p>}
  </div>;
}
