import { useEffect, useRef, useState } from 'react';
import { Loader2, Film, Download, ChevronDown, AlertCircle } from 'lucide-react';
import {
  getBudget, getLibrary, getVideoOptions, generateVideo, getVideoJob, fetchVideoBlobUrl,
} from '../lib/sidecar';
import Dictate from '../components/Dictate';
import type { LocalModel, VideoJob, MemoryBudget } from '../lib/sidecar';

/** LTX honours frame counts of the form 8n+1; anything else is padded silently. */
const FRAME_CHOICES = [
  { n: 25, label: '1s' },
  { n: 49, label: '2s' },
  { n: 97, label: '4s' },
  { n: 145, label: '6s' },
  { n: 193, label: '8s' },
  { n: 241, label: '10s' },
];

const SIZES = [
  { w: 448, h: 256, label: '448×256', tier: 'Draft' },
  { w: 512, h: 320, label: '512×320', tier: 'Draft' },
  { w: 640, h: 384, label: '640×384', tier: 'Preview' },
  { w: 704, h: 480, label: '704×480', tier: 'Balanced' },
  { w: 960, h: 544, label: '960×544', tier: 'Sharp' },
  { w: 1216, h: 704, label: '1216×704', tier: 'Max detail' },
  // Wan's native size. Not a nicety for that family — below it the model
  // returns moving colour rather than a worse clip.
  { w: 1280, h: 704, label: '1280×704', tier: 'Native' },
];

const QUALITY_NEGATIVE = 'worst quality, inconsistent motion, blurry, jittery, distorted';

export default function VideoView() {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState<LocalModel | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);

  const [prompt, setPrompt] = useState('');
  const [negative, setNegative] = useState(QUALITY_NEGATIVE);
  const [frames, setFrames] = useState(49);
  const [size, setSize] = useState(SIZES[4]);
  const [steps, setSteps] = useState(40);

  // Checked before starting, not discovered during. macOS refuses an oversized
  // allocation and the job dies with a message; a machine with a discrete GPU
  // can lock up hard enough to need a power cycle.
  const [budget, setBudget] = useState<MemoryBudget | null>(null);
  useEffect(() => {
    let cancelled = false;
    getBudget({ frames, width: size.w, height: size.h, model_path: model?.path })
      .then((b) => { if (!cancelled) setBudget(b); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [frames, size.w, size.h, model?.path]);
  const [guidance, setGuidance] = useState(3.0);

  const [job, setJob] = useState<VideoJob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const lastUrl = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const loadModels = async (attempt = 0) => {
      try {
        const list = await getLibrary();
        if (cancelled) return;
        const v = list.filter((m) => m.category === 'video');
        setModels(v);
        setModel((p) => p ?? v[0] ?? null);
        if (v.length === 0 && attempt < 2) {
          retryTimer = window.setTimeout(() => void loadModels(attempt + 1), 800);
          return;
        }
        setLibraryLoading(false);
      } catch {
        if (cancelled) return;
        if (attempt < 2) {
          retryTimer = window.setTimeout(() => void loadModels(attempt + 1), 800);
        } else {
          setLibraryLoading(false);
        }
      }
    };
    void loadModels();
    // Take the engine's defaults rather than duplicating them here.
    getVideoOptions()
      .then((o) => {
        setFrames(o.default_frames);
        setSteps(o.default_steps);
        setGuidance(o.default_guidance);
        setNegative(o.default_negative_prompt);
        const match = SIZES.find((s) => s.w === o.default_width && s.h === o.default_height);
        if (match) setSize(match);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, []);

  useEffect(() => {
    if (!job || job.done) return;
    const t = window.setInterval(async () => {
      const next = await getVideoJob(job.id).catch(() => null);
      if (!next) return;
      setJob(next);
      if (next.done && next.status === 'done') {
        if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
        const u = await fetchVideoBlobUrl(next.id).catch(() => null);
        lastUrl.current = u;
        setUrl(u);
      }
    }, 2000);
    return () => window.clearInterval(t);
  }, [job]);

  async function run() {
    if (!model || !prompt.trim() || (job && !job.done)) return;
    setUrl(null);
    setJob(await generateVideo(model.path, prompt.trim(), {
      negative_prompt: negative.trim(),
      frames, width: size.w, height: size.h, steps, guidance,
    }));
  }

  const busy = !!job && !job.done;
  const pct = job && job.total_steps ? (job.step / job.total_steps) * 100 : 0;

  // A machine under the floor is told so once, rather than failing the same
  // way on every combination of length and size it tries.
  if (budget?.video && !budget.video.runnable) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="max-w-md text-center">
          <Film size={28} className="mx-auto mb-4 text-[var(--text-faint)]" />
          <h2 className="text-sm mb-2">Video needs more memory than this Mac has</h2>
          <p className="text-[11px] text-[var(--text-faint)] leading-relaxed">
            {budget.video.reason} A single job can use about{' '}
            {budget.video.budget_gb} GB here, and the shortest draft clip needs
            more than that before it renders a frame.
          </p>
          <p className="text-[11px] text-[var(--text-faint)] leading-relaxed mt-3">
            Image, Music and Voice are unaffected — they run in a fraction of
            the memory. Video models are held whole while they denoise, so
            there is no smaller setting that would make this one fit.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      <div className="w-[320px] shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5">
        <div className="relative">
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Model</label>
          <button
            onClick={() => setPickerOpen((v) => !v)}
            className="mt-1.5 w-full flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-[var(--bg-inset)] hover:bg-[var(--bg-inset)]/70 transition"
          >
            <span className={model ? '' : 'text-[var(--text-faint)]'}>
              {model ? model.name : libraryLoading ? 'Finding video models…' : 'No video model installed'}
            </span>
            <ChevronDown size={13} className="text-[var(--text-faint)]" />
          </button>
          {pickerOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 card p-1.5 z-20 shadow-2xl">
              {models.length === 0 && (
                <div className="text-[11px] text-[var(--text-faint)] px-2 py-3 text-center">
                  Install a video model from the Models tab.
                </div>
              )}
              {models.map((m) => (
                <button
                  key={m.id}
                  onClick={() => { setModel(m); setPickerOpen(false); }}
                  className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition text-xs"
                >
                  {m.name}
                  <span className="block text-[10px] text-[var(--text-faint)]">
                    {m.size_gb.toFixed(1)} GB
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Length</label>
          <div className="mt-1.5 flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg">
            {FRAME_CHOICES.map((f) => (
              <button
                key={f.n}
                onClick={() => setFrames(f.n)}
                className={`flex-1 text-[11px] py-1.5 rounded-md transition ${
                  frames === f.n ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Size</label>
          <div className="mt-1.5 grid grid-cols-2 gap-1">
            {SIZES.map((s) => (
              <button
                key={s.label}
                onClick={() => setSize(s)}
                className={`text-[11px] py-1.5 rounded-md transition ${
                  size.label === s.label ? 'bg-[var(--bg-raised)] text-white' : 'bg-[var(--bg-inset)] text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                <span className="block">{s.label}</span>
                <span className="block text-[9px] opacity-60 mt-0.5">{s.tier}</span>
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-[var(--text-faint)] leading-relaxed">
            960×544 is the sharp everyday preset; 704×480 is the faster balance.
            Max detail is slower but still guarded by the live memory check. Past
            ~10s the model can drift, so quality gives out before memory does.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Steps</span>
            <input
              type="number" min={10} max={60} value={steps}
              onChange={(e) => setSteps(Number(e.target.value))}
              className="bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Guidance</span>
            <input
              type="number" min={1} max={10} step={0.5} value={guidance}
              onChange={(e) => setGuidance(Number(e.target.value))}
              className="bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none"
            />
          </label>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Avoid</label>
            <Dictate title="Dictate what to avoid" onText={(t) => setNegative((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
          <input
            value={negative}
            onChange={(e) => setNegative(e.target.value)}
            placeholder={QUALITY_NEGATIVE}
            className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none placeholder:text-[var(--text-faint)]"
          />
        </div>

        {budget?.estimate && (
          <div className={`text-[11px] leading-relaxed rounded-lg px-3 py-2 ${
            budget.fits === false
              ? 'bg-rose-950/40 border border-rose-500/30 text-rose-300'
              : budget.tight
                ? 'bg-amber-950/30 border border-amber-500/25 text-amber-300/90'
                : 'text-[var(--text-faint)]'
          }`}>
            {budget.fits === false ? (
              <>
                <strong>Will not fit.</strong> Needs about {budget.estimate.total_gb} GB
                against {budget.budget.budget_gb} GB available on this machine. Choose a
                shorter clip or a smaller size — on some systems an overrun locks the
                machine up rather than failing cleanly.
              </>
            ) : budget.tight ? (
              <>
                <strong>Tight.</strong> About {budget.estimate.total_gb} GB of
                {' '}{budget.budget.budget_gb} GB. It should run, but the machine will be
                slow while it does.
              </>
            ) : (
              <>
                ~{budget.estimate.total_gb} GB of {budget.budget.budget_gb} GB
                {' · '}{budget.estimate.weights_gb} GB weights
                {' + '}{budget.estimate.sequence_gb} GB for {budget.estimate.tokens.toLocaleString()} tokens
              </>
            )}
          </div>
        )}

        <button
          onClick={run}
          disabled={!model || !prompt.trim() || busy || budget?.fits === false}
          className="h-10 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Film size={14} />}
          {busy ? (job?.stage || 'Generating…') : 'Generate'}
        </button>
      </div>

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="p-6 pb-3">
          <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Prompt</label>
            <Dictate title="Dictate the prompt" onText={(t) => setPrompt((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="A slow drone shot over a foggy pine forest at dawn, mist moving between the trees…"
            className="mt-1.5 w-full h-24 bg-[var(--bg-inset)] rounded-lg px-3 py-3 text-sm outline-none resize-none leading-relaxed placeholder:text-[var(--text-faint)]"
          />
          <p className="mt-2 text-[10px] text-[var(--text-faint)] leading-relaxed">
            Describe one continuous shot in chronological order: camera movement,
            main subject, action, then scene details. Crowded scenes are harder for
            this 2B model, so keep important actions explicit.
          </p>
        </div>

        <div className="flex-1 min-h-0 px-6 pb-6 flex items-center justify-center">
          {url ? (
            <div className="card p-4 max-w-full">
              <video src={url} controls loop autoPlay muted className="rounded-lg max-h-[52vh]" />
              <div className="flex items-center justify-between mt-3">
                <span className="text-[10px] text-[var(--text-faint)]">
                  {size.label} · {frames} frames
                </span>
                <button
                  onClick={() => {
                    const a = document.createElement('a');
                    a.href = url; a.download = `uncloud-video-${job?.id}.mp4`; a.click();
                  }}
                  className="flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition"
                >
                  <Download size={12} /> Save
                </button>
              </div>
            </div>
          ) : job?.status === 'error' ? (
            <div className="card p-4 max-w-md border-rose-500/30">
              <div className="flex items-center gap-2 text-rose-400">
                <AlertCircle size={14} />
                <span className="text-xs font-medium">Generation failed</span>
              </div>
              <p className="mt-2 text-[11px] text-[var(--text-dim)] whitespace-pre-wrap leading-relaxed">
                {job.error}
              </p>
            </div>
          ) : busy ? (
            <div className="w-full max-w-sm">
              <div className="flex items-center gap-2 text-sm text-[var(--text-dim)] mb-3">
                <Loader2 size={14} className="animate-spin" />
                {job?.stage || 'Working'}
                {job && job.total_steps > 0 && ` — step ${job.step} of ${job.total_steps}`}
              </div>
              <div className="h-1 rounded-full bg-[var(--bg-inset)] overflow-hidden">
                <div className="h-full accent-bar transition-[width] duration-500" style={{ width: `${Math.max(2, pct)}%` }} />
              </div>
            </div>
          ) : (
            <p className="text-sm text-[var(--text-faint)]">
              {models.length
                ? 'Describe a shot and generate.'
                : libraryLoading ? 'Finding video models…' : 'No video model installed.'}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
