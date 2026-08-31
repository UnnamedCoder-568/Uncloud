import { useEffect, useState } from 'react';
import { ChevronDown, Sparkles, Loader2, SlidersHorizontal, Shuffle } from 'lucide-react';
import { getLibrary, generateImage, getImageJob, fetchImageBlobUrl } from '../lib/sidecar';
import type { LocalModel, ImageJob } from '../lib/sidecar';

function defaultsFor(engine: string | undefined) {
  return engine === 'mflux' ? { steps: 8, guidance: 1.0 } : { steps: 25, guidance: 7.0 };
}

export default function ImageGenerate() {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [steps, setSteps] = useState(8);
  const [guidance, setGuidance] = useState(1.0);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [seed, setSeed] = useState('');
  const [job, setJob] = useState<ImageJob | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  useEffect(() => {
    getLibrary().then((list) => {
      const images = list.filter((m) => m.category === 'image' && m.ready && m.capabilities.includes('text2img'));
      setModels(images);
      setModel((prev) => {
        const next = prev ?? images[0] ?? null;
        const d = defaultsFor(next?.engine);
        setSteps(d.steps);
        setGuidance(d.guidance);
        return next;
      });
    });
  }, []);

  useEffect(() => {
    if (!job || job.done) return;
    const t = setInterval(async () => {
      const updated = await getImageJob(job.id);
      setJob(updated);
      if (updated.done && updated.status === 'done') {
        setImageUrl(await fetchImageBlobUrl(updated.id));
      }
    }, 800);
    return () => clearInterval(t);
  }, [job]);

  function selectModel(m: LocalModel) {
    setModel(m);
    setPickerOpen(false);
    const d = defaultsFor(m.engine);
    setSteps(d.steps);
    setGuidance(d.guidance);
  }

  async function generate() {
    if (!model || !prompt.trim()) return;
    setImageUrl(null);
    const newJob = await generateImage(model.path, model.engine, prompt.trim(), model.catalog_id, {
      negative_prompt: negativePrompt.trim() || undefined,
      steps, guidance, width, height,
      seed: seed.trim() ? Number(seed.trim()) : undefined,
    });
    setJob(newJob);
  }

  const running = job && !job.done;

  return (
    <div className="h-full flex">
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 shrink-0 border-b border-[var(--border-soft)] flex items-center px-5 relative">
          <button
            className="flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg hover:bg-[var(--bg-raised)] transition"
            onClick={() => setPickerOpen((v) => !v)}
          >
            {model ? (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>{model.name}</span>
              </>
            ) : (
              <span className="text-[var(--text-faint)]">No image model installed</span>
            )}
            <ChevronDown size={14} className="text-[var(--text-faint)]" />
          </button>

          {pickerOpen && (
            <div className="absolute top-14 left-5 w-96 card p-1.5 z-10 shadow-2xl max-h-80 overflow-y-auto">
              {models.length === 0 && (
                <div className="text-xs text-[var(--text-faint)] px-3 py-4 text-center">
                  No image models found yet. Download one from the Models tab.
                </div>
              )}
              {models.map((m) => {
                // Only these two have generation pipelines behind them. The rest
                // are listed so it's clear they were found, not hidden as though
                // they were never there.
                const usable = m.engine === 'mflux' || m.engine === 'diffusers';
                return (
                  <button
                    key={m.id}
                    onClick={() => usable && selectModel(m)}
                    disabled={!usable}
                    title={m.note || undefined}
                    className={`w-full text-left px-3 py-2 rounded-lg transition ${
                      usable ? 'hover:bg-[var(--bg-inset)]' : 'opacity-45 cursor-not-allowed'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-sm truncate">{m.name}</span>
                      <span className="text-[10px] font-mono text-[var(--text-faint)] uppercase shrink-0">
                        {usable ? m.engine : 'unsupported'}
                      </span>
                    </span>
                    {!usable && m.note && (
                      <span className="block text-[10px] text-amber-400/70 mt-0.5 leading-snug">
                        {m.note}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          <button
            onClick={() => setOptionsOpen((v) => !v)}
            title="Generation options"
            className={`ml-auto flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition ${
              optionsOpen ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50'
            }`}
          >
            <SlidersHorizontal size={13} /> Options
          </button>
        </header>

        <div className="flex-1 flex items-center justify-center p-6 overflow-hidden">
          {imageUrl ? (
            <img src={imageUrl} alt={prompt} className="max-h-full max-w-full rounded-xl border border-[var(--border)]" />
          ) : running ? (
            <div className="flex flex-col items-center gap-3 text-[var(--text-dim)]">
              <Loader2 size={22} className="animate-spin" />
              <span className="text-sm">
                {job.total_steps ? `Generating — step ${job.step}/${job.total_steps}` : 'Generating…'}
              </span>
              {model?.engine === 'mflux' && (
                <span className="text-[11px] text-[var(--text-faint)]">First run loads ~22GB into memory — this can take a few minutes.</span>
              )}
            </div>
          ) : job?.status === 'error' ? (
            <div className="text-sm text-rose-400 max-w-md text-center">{job.error}</div>
          ) : (
            <div className="text-sm text-[var(--text-faint)]">Describe an image below to get started.</div>
          )}
        </div>

        <div className="p-4 border-t border-[var(--border-soft)]">
          <div className="max-w-2xl mx-auto flex flex-col gap-2">
            <div className="flex items-end gap-2 card px-3 py-2 focus-within:border-[#3a3a42]">
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={model ? 'A cabin in the woods at dusk, cinematic lighting…' : 'Install an image model first'}
                disabled={!model}
                rows={2}
                className="flex-1 bg-transparent outline-none resize-none text-sm py-1 placeholder:text-[var(--text-faint)]"
              />
              <button
                onClick={generate}
                disabled={!model || !prompt.trim() || !!running}
                className="w-8 h-8 rounded-full btn-accent flex items-center justify-center disabled:opacity-30 transition shrink-0"
              >
                {running ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              </button>
            </div>
            <input
              value={negativePrompt}
              onChange={(e) => setNegativePrompt(e.target.value)}
              placeholder="Negative prompt (optional)"
              className="bg-transparent outline-none text-xs px-1 text-[var(--text-dim)] placeholder:text-[var(--text-faint)]"
            />
          </div>
        </div>
      </div>

      {optionsOpen && (
        <div className="w-64 shrink-0 border-l border-[var(--border-soft)] p-4 overflow-y-auto flex flex-col gap-4">
          <h3 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Generation options</h3>

          <label className="flex flex-col gap-1.5">
            <span className="text-xs text-[var(--text-dim)]">Steps</span>
            <input
              type="number" min={1} max={100} value={steps}
              onChange={(e) => setSteps(Math.max(1, Number(e.target.value) || 1))}
              className="card px-2.5 py-1.5 text-sm bg-transparent outline-none focus:border-[#3a3a42]"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-xs text-[var(--text-dim)]">Guidance</span>
            <input
              type="number" min={0} max={20} step={0.1} value={guidance}
              onChange={(e) => setGuidance(Number(e.target.value) || 0)}
              className="card px-2.5 py-1.5 text-sm bg-transparent outline-none focus:border-[#3a3a42]"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-[var(--text-dim)]">Width</span>
              <input
                type="number" min={256} max={2048} step={64} value={width}
                onChange={(e) => setWidth(Number(e.target.value) || 1024)}
                className="card px-2.5 py-1.5 text-sm bg-transparent outline-none focus:border-[#3a3a42]"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-[var(--text-dim)]">Height</span>
              <input
                type="number" min={256} max={2048} step={64} value={height}
                onChange={(e) => setHeight(Number(e.target.value) || 1024)}
                className="card px-2.5 py-1.5 text-sm bg-transparent outline-none focus:border-[#3a3a42]"
              />
            </label>
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-xs text-[var(--text-dim)]">Seed</span>
            <div className="flex gap-1.5">
              <input
                type="text" value={seed} placeholder="random"
                onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ''))}
                className="card flex-1 min-w-0 px-2.5 py-1.5 text-sm bg-transparent outline-none focus:border-[#3a3a42]"
              />
              <button
                title="Clear seed (random each time)"
                onClick={() => setSeed('')}
                className="card w-8 shrink-0 flex items-center justify-center hover:border-[#3a3a42] transition"
              >
                <Shuffle size={13} className="text-[var(--text-faint)]" />
              </button>
            </div>
          </label>

          {model && (
            <button
              onClick={() => { const d = defaultsFor(model.engine); setSteps(d.steps); setGuidance(d.guidance); setWidth(1024); setHeight(1024); setSeed(''); }}
              className="text-xs text-[var(--text-faint)] hover:text-[var(--text-dim)] transition text-left"
            >
              Reset to defaults
            </button>
          )}
        </div>
      )}
    </div>
  );
}
