import { useEffect, useState } from 'react';
import { fetchImageBlobUrl } from '../lib/sidecar';
import type { ImageJob } from '../lib/sidecar';

/** The default preview is the finished enhanced copy. Fetch the original only
 * for this authenticated job, and release it when the viewer closes. */
export default function EnhancedImageComparison({ job, onView }: {
  job: ImageJob;
  onView: (view: { src: string; name: string } | null) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [original, setOriginal] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let dead = false, made: string | null = null;
    void fetchImageBlobUrl(job.id, true).then(value => {
      if (dead) { URL.revokeObjectURL(value); return; }
      made = value; setUrl(value);
    }).catch(e => { if (!dead) setError(String(e)); });
    return () => { dead = true; if (made) URL.revokeObjectURL(made); };
  }, [job.id]);
  function show(value: boolean) {
    setOriginal(value);
    onView(value && url ? { src: url, name: job.original_path?.split(/[\\/]/).pop() ?? 'original.png' } : null);
  }
  return <div className="image-enhancement-panel">
    <div className="flex flex-wrap items-center gap-2">
      <button className="image-enhancement-button" disabled={!url} aria-pressed={original} onClick={() => show(true)}>Original</button>
      <button className="image-enhancement-button" aria-pressed={!original} onClick={() => show(false)}>Enhanced 2×</button>
      <span className="text-xs text-[var(--text-faint)]">Auto-enhanced · original preserved</span>
    </div>
    {error && <p role="alert" className="text-xs mt-1">{error}</p>}
  </div>;
}
