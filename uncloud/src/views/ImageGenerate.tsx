import { useEffect, useState } from 'react';
import { ChevronDown, Loader2, Shuffle, SlidersHorizontal, Sparkles, UserRound, UserRoundPlus } from 'lucide-react';
import { getLibrary, generateImage, editImage, getImageJob, fetchImageBlobUrl,
         listCharacters, saveCharacter } from '../lib/sidecar';
import Dictate from '../components/Dictate';
import SaveActions from '../components/SaveActions';
import type { LocalModel, ImageJob, Character } from '../lib/sidecar';

// Models that carry their own settings win: a distilled checkpoint run at the
// 25-step default is a minute of work for a picture it makes in four.
function defaultsFor(model: LocalModel | null | undefined) {
  const base =
    model?.engine === 'mflux' ? { steps: 8, guidance: 1.0 }
    : model?.engine === 'flux2-profile' ? { steps: 4, guidance: 1.0 }
    : { steps: 25, guidance: 7.0 };
  return {
    steps: model?.defaults?.steps ?? base.steps,
    guidance: model?.defaults?.guidance ?? base.guidance,
  };
}

// Engines with a generation path behind them. The rest are listed so it's clear
// they were found, rather than hidden as though they were never there.
const USABLE = new Set(['mflux', 'diffusers', 'flux2-profile']);

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

  //: The subject to keep consistent across generations. Creating a character
  //  was already possible; using one was not, which made the feature a filing
  //  cabinet rather than a tool.
  const [characters, setCharacters] = useState<Character[]>([]);
  const [characterSlug, setCharacterSlug] = useState('');
  const character = characters.find((c) => c.slug === characterSlug) ?? null;

  useEffect(() => {
    getLibrary().then((list) => {
      // Not-ready models stay in the list, disabled: the picker shows their
      // note, which says what is missing. Filtering them out leaves someone
      // hunting for a model the app can see and they cannot.
      const images = list
        .filter((m) => m.category === 'image' && m.capabilities.includes('text2img'))
        .sort((a, b) => Number(b.ready) - Number(a.ready));
      setModels(images);
      setModel((prev) => {
        const next = prev ?? images.find((m) => m.ready && USABLE.has(m.engine)) ?? null;
        const d = defaultsFor(next);
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
    const d = defaultsFor(m);
    setSteps(d.steps);
    setGuidance(d.guidance);
  }

  // Present only when an encoder component is installed. Klein's encoder is a
  // causal LM, which is where its restraint lives; other pipelines ignore this.
  const [encoder, setEncoder] = useState<LocalModel | null>(null);
  const [useEncoder, setUseEncoder] = useState(false);

  useEffect(() => {
    getLibrary()
      .then((ms) => setEncoder(ms.find((m) => m.engine === 'text-encoder') ?? null))
      .catch(() => undefined);
  }, []);

  const encoderApplies =
    !!encoder && (model?.engine === 'diffusers' || model?.engine === 'flux2-profile');

  const loadCharacters = () => listCharacters().then(setCharacters).catch(() => undefined);
  useEffect(() => { loadCharacters(); }, []);

  // Identity carries far more strongly from a reference image than from a
  // description, but only a model that can edit from a reference can use one.
  const canUseReference =
    !!character?.has_reference && !!model?.capabilities.includes('edit');

  async function generate() {
    if (!model || !prompt.trim()) return;
    setImageUrl(null);

    // A character's description goes into the prompt either way; the reference
    // image is what actually holds the likeness, so use it when we can.
    const described = character?.description
      ? `${character.description.trim()}. ${prompt.trim()}`
      : prompt.trim();

    if (canUseReference && character?.reference_path) {
      setJob(await editImage(model.path, described, character.reference_path,
                             model.catalog_id, {
        steps, guidance, width, height,
        seed: seed.trim() ? Number(seed.trim()) : undefined,
      }));
      return;
    }

    const newJob = await generateImage(model.path, model.engine, described, model.catalog_id, {
      negative_prompt: negativePrompt.trim() || undefined,
      steps, guidance, width, height,
      seed: seed.trim() ? Number(seed.trim()) : undefined,
      text_encoder_path: encoderApplies && useEncoder ? encoder!.path : undefined,
      // Set for MLX checkpoints found on disk; catalog models leave these
      // unset and the engine falls back to the catalog's own entry point.
      mflux_cli: model.mflux_cli ?? undefined,
      mflux_base: model.mflux_base ?? undefined,
      lora_paths: model.lora_paths?.length ? model.lora_paths : undefined,
      lora_scales: model.lora_scales?.length ? model.lora_scales : undefined,
    });
    setJob(newJob);
  }

  const running = job && !job.done;

  /** Promote the picture on screen into a reusable subject.
   *
   *  This is the other half of the loop: generate someone you like, keep them,
   *  and every later generation can be of the same person. Without it a
   *  character could only ever be a photograph you already had. */
  const [savingCharacter, setSavingCharacter] = useState(false);
  async function keepAsCharacter(existing: Character | null) {
    const path = job?.output_path;
    if (!path) return;
    const name = existing?.name
      ?? window.prompt('Name this character')?.trim();
    if (!name) return;
    setSavingCharacter(true);
    try {
      const saved = await saveCharacter({
        name,
        description: existing?.description ?? '',
        tags: existing?.tags ?? [],
        reference_path: path,
        slug: existing?.slug ?? null,
      });
      await loadCharacters();
      setCharacterSlug(saved.slug);
    } finally {
      setSavingCharacter(false);
    }
  }

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
                const usable = USABLE.has(m.engine) && m.ready;
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
            <div className="flex flex-col items-center gap-2 max-h-full min-h-0">
              <img
                src={imageUrl}
                alt={prompt}
                className="min-h-0 max-h-full max-w-full object-contain rounded-xl border border-[var(--border)]"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={() => keepAsCharacter(null)}
                  disabled={savingCharacter || !job?.output_path}
                  className="text-xs px-3 py-1.5 rounded-lg border border-[var(--border)] text-[var(--text-dim)] hover:text-white hover:bg-[var(--bg-raised)] transition disabled:opacity-40"
                >
                  <UserRoundPlus size={13} className="inline mr-1.5 -mt-0.5" />
                  Save as character
                </button>
                {character && (
                  <button
                    onClick={() => keepAsCharacter(character)}
                    disabled={savingCharacter}
                    className="text-xs px-3 py-1.5 rounded-lg border border-[var(--border)] text-[var(--text-dim)] hover:text-white hover:bg-[var(--bg-raised)] transition disabled:opacity-40"
                    title={`Replace ${character.name}'s reference with this picture`}
                  >
                    Use as {character.name}'s reference
                  </button>
                )}
              </div>
              <SaveActions
                path={job?.output_path ?? null}
                onDiscarded={() => {
                  URL.revokeObjectURL(imageUrl);
                  setImageUrl(null);
                  setJob(null);
                }}
              />
            </div>
          ) : running ? (
            <div className="flex flex-col items-center gap-3 text-[var(--text-dim)]">
              <Loader2 size={22} className="animate-spin" />
              <span className="text-sm">
                {job.total_steps ? `Generating — step ${job.step}/${job.total_steps}` : 'Generating…'}
              </span>
              {model?.engine === 'mflux' && (
                <span className="text-[11px] text-[var(--text-faint)]">
                  {job && job.step > 0
                    ? 'Model is loaded — rendering.'
                    : 'Loading the model into memory. It stays loaded, so the next generation with this model skips this.'}
                </span>
              )}
              {/* An assembled pipeline has two halves that do not fit in memory
                  together, so a new prompt means loading the encoder, then
                  swapping it for the image model. Saying "it stays loaded"
                  here would be a lie the timer immediately exposes. */}
              {model?.engine === 'flux2-profile' && (
                <span className="text-[11px] text-[var(--text-faint)] max-w-sm text-center leading-relaxed">
                  {job && job.step > 0
                    ? 'Rendering.'
                    : 'Reading your prompt, then loading the image model — this pipeline is '
                      + 'too big to hold both at once, so a new prompt costs one swap. '
                      + 'Same prompt on a new seed skips straight to rendering.'}
                </span>
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
                placeholder={model
                  ? 'A cabin in the woods at dusk, cinematic lighting…'
                  : 'Describe your image — install a model from Models to render it'}
                // Not disabled: a prompt is worth writing before the model that
                // will render it exists. Only the render button is gated.
                rows={2}
                className="flex-1 bg-transparent outline-none resize-none text-sm py-1 placeholder:text-[var(--text-faint)]"
              />
              <Dictate
                title="Dictate the prompt"
                onText={(t) => setPrompt((v) => (v ? v.trimEnd() + ' ' + t : t))}
                className="mb-0.5"
              />
              <button
                onClick={generate}
                disabled={!model || !prompt.trim() || !!running}
                className="w-8 h-8 rounded-full btn-accent flex items-center justify-center disabled:opacity-30 transition shrink-0"
              >
                {running ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              </button>
            </div>
            {/* Who this is of. Sits with the prompt because it is part of
                describing the picture, not a generation setting. */}
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-[var(--text-faint)]">
                <UserRound size={13} />
                <select
                  value={characterSlug}
                  onChange={(e) => setCharacterSlug(e.target.value)}
                  className="bg-transparent outline-none text-xs text-[var(--text-dim)] cursor-pointer"
                >
                  <option value="">No character</option>
                  {characters.map((c) => (
                    <option key={c.slug} value={c.slug}>{c.name}</option>
                  ))}
                </select>
              </label>
              {character && (
                <span className="text-[11px] text-[var(--text-faint)]">
                  {canUseReference
                    ? 'Using their reference image — likeness carries.'
                    : character.has_reference
                      ? 'This model cannot generate from a reference, so only the description is used. The likeness will drift.'
                      : 'No reference image saved, so only the description is used. Generate one and keep it below.'}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1">
              <input
                value={negativePrompt}
                onChange={(e) => setNegativePrompt(e.target.value)}
                placeholder="Negative prompt (optional)"
                className="flex-1 bg-transparent outline-none text-xs px-1 text-[var(--text-dim)] placeholder:text-[var(--text-faint)]"
              />
              <Dictate
                title="Dictate what to avoid"
                onText={(t) => setNegativePrompt((v) => (v ? v.trimEnd() + ' ' + t : t))}
              />
            </div>
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

          {encoderApplies && (
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={useEncoder}
                onChange={(e) => setUseEncoder(e.target.checked)}
                className="mt-0.5 accent-[var(--accent)]"
              />
              <span className="min-w-0">
                <span className="text-xs block">Uncensored text encoder</span>
                <span className="text-[10px] text-[var(--text-faint)] block leading-snug">
                  Swaps this pipeline's text encoder for {encoder!.name}. Only affects
                  models whose encoder is a language model — FLUX.2 Klein. Models
                  that already bring their own encoder are unchanged by this.
                </span>
              </span>
            </label>
          )}

          {model && (
            <button
              onClick={() => { const d = defaultsFor(model); setSteps(d.steps); setGuidance(d.guidance); setWidth(1024); setHeight(1024); setSeed(''); }}
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
