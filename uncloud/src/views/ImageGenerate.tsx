import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, LayoutGrid, Loader2, Shuffle, SlidersHorizontal, Sparkles, UserRound, UserRoundPlus } from 'lucide-react';
import { getLibrary, generateImage, editImage, getImageJob, fetchImageBlobUrl,
         listCharacters, saveCharacter } from '../lib/sidecar';
import Dictate from '../components/Dictate';
import SaveActions from '../components/SaveActions';
import AddFromDisk from '../components/AddFromDisk';
import { useLibraryVersion } from '../lib/library-changed';
import type { LocalModel, ImageJob, Character } from '../lib/sidecar';
import { onCharacterListChange } from '../lib/characters-changed';
import { isNarrow } from '../lib/platform';

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
  const libraryVersion = useLibraryVersion();
  const [model, setModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  // Open beside the canvas on a desktop. On a phone it would take two thirds
  // of the width, so there it starts closed and opens over the canvas instead.
  const [optionsOpen, setOptionsOpen] = useState(() => !isNarrow());
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [steps, setSteps] = useState(8);
  const [guidance, setGuidance] = useState(1.0);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [seed, setSeed] = useState('');
  //: How many images one press makes. Remembered: people who want four
  //  options want four every time.
  const [count, setCount] = useState(() => {
    try { return Math.min(8, Math.max(1, Number(localStorage.getItem('uncloud.image.count')) || 1)); }
    catch { return 1; }
  });
  useEffect(() => {
    try { localStorage.setItem('uncloud.image.count', String(count)); } catch { /* storage refused */ }
  }, [count]);
  //: Every job the last press started, and the pictures that have finished.
  const [batch, setBatch] = useState<ImageJob[]>([]);
  const [urls, setUrls] = useState<Record<string, string>>({});
  //: The image shown large. In a batch, none until one is chosen from the grid.
  const [focus, setFocus] = useState<string | null>(null);
  const job = batch.find((j) => j.id === focus) ?? (batch.length === 1 ? batch[0] : null);
  const imageUrl = job ? urls[job.id] ?? null : null;

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
  }, [libraryVersion]);

  useEffect(() => {
    if (!batch.some((j) => !j.done)) return;
    const t = setInterval(async () => {
      const pending = batch.filter((j) => !j.done);
      const updated = await Promise.all(pending.map((j) => getImageJob(j.id).catch(() => j)));
      const byId = new Map(updated.map((j) => [j.id, j]));
      setBatch((current) => current.map((j) => byId.get(j.id) ?? j));
      for (const u of updated) {
        if (u.done && u.status === 'done') {
          const url = await fetchImageBlobUrl(u.id).catch(() => null);
          if (url) setUrls((m) => ({ ...m, [u.id]: url }));
        }
      }
    }, 800);
    return () => clearInterval(t);
  }, [batch]);

  /** Forget one image — it was discarded, file and all. */
  function forget(id: string) {
    setUrls((m) => {
      if (m[id]) URL.revokeObjectURL(m[id]);
      const next = { ...m };
      delete next[id];
      return next;
    });
    setBatch((b) => b.filter((j) => j.id !== id));
    setFocus(null);
  }

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
  }, [libraryVersion]);

  const encoderApplies =
    !!encoder && (model?.engine === 'diffusers' || model?.engine === 'flux2-profile');

  const loadCharacters = useCallback(
    () => listCharacters().then(setCharacters).catch(() => undefined), []);
  useEffect(() => {
    loadCharacters();
    // Saved in the Characters tab, chosen here. Without this the picker only
    // caught up after a restart, which made the feature look broken to anyone
    // who used it in the obvious order.
    return onCharacterListChange(loadCharacters);
  }, [loadCharacters]);

  // Identity carries far more strongly from a reference image than from a
  // description, but only a model that can edit from a reference can use one.
  const canUseReference =
    !!character?.has_reference && !!model?.capabilities.includes('edit');

  function begin(started: ImageJob) {
    Object.values(urls).forEach((u) => URL.revokeObjectURL(u));
    setUrls({});
    const jobs = started.batch?.length ? started.batch : [started];
    setBatch(jobs);
    setFocus(jobs.length === 1 ? jobs[0].id : null);
  }

  async function generate() {
    if (!model || !prompt.trim()) return;

    // A character's description goes into the prompt either way; the reference
    // image is what actually holds the likeness, so use it when we can.
    const described = character?.description
      ? `${character.description.trim()}. ${prompt.trim()}`
      : prompt.trim();

    if (canUseReference && character?.reference_path) {
      begin(await editImage(model.path, described, character.reference_path,
                            model.catalog_id, {
        steps, guidance, width, height, count,
        seed: seed.trim() ? Number(seed.trim()) : undefined,
      }));
      return;
    }

    const newJob = await generateImage(model.path, model.engine, described, model.catalog_id, {
      negative_prompt: negativePrompt.trim() || undefined,
      steps, guidance, width, height, count,
      seed: seed.trim() ? Number(seed.trim()) : undefined,
      text_encoder_path: encoderApplies && useEncoder ? encoder!.path : undefined,
      // Set for MLX checkpoints found on disk; catalog models leave these
      // unset and the engine falls back to the catalog's own entry point.
      mflux_cli: model.mflux_cli ?? undefined,
      mflux_base: model.mflux_base ?? undefined,
      lora_paths: model.lora_paths?.length ? model.lora_paths : undefined,
      lora_scales: model.lora_scales?.length ? model.lora_scales : undefined,
    });
    begin(newJob);
  }

  const running = batch.some((j) => !j.done);
  //: The one rendering now, for the progress line.
  const current = batch.find((j) => j.status === 'running') ?? batch.find((j) => !j.done) ?? null;

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
            <div className="absolute top-14 left-5 w-96 max-w-[calc(100vw-2.5rem)] card p-1.5 z-10 shadow-2xl max-h-80 overflow-y-auto">
              {models.length === 0 && (
                <div className="text-xs text-[var(--text-faint)] px-3 py-4 text-center">
                  No image models found yet. Download one from the Models tab, or add one you already have.
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
              {/* Pinned: the list scrolls, and an option below the fold is one nobody finds. */}
              <div className="sticky -bottom-1.5 -mx-1.5 -mb-1.5 px-1.5 pb-1.5 bg-inherit border-t border-[var(--border-soft)] mt-1 pt-1">
                <AddFromDisk onOpen={() => setPickerOpen(false)} />
              </div>
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
          {batch.length > 1 && !focus ? (
            <div className="w-full h-full overflow-y-auto">
              <div className={`grid gap-3 ${batch.length <= 4 ? 'grid-cols-2' : 'grid-cols-4 max-lg:grid-cols-3'} max-md:grid-cols-2`}>
                {batch.map((j) => (
                  <button key={j.id} onClick={() => urls[j.id] && setFocus(j.id)}
                          disabled={!urls[j.id]}
                          className="relative aspect-square rounded-xl border border-[var(--border)] bg-[var(--bg-inset)] overflow-hidden flex items-center justify-center">
                    {urls[j.id] ? (
                      <img src={urls[j.id]} alt={j.label ?? prompt} className="w-full h-full object-cover" />
                    ) : j.status === 'error' ? (
                      <span className="text-[11px] text-rose-400 px-3 text-center">{j.error}</span>
                    ) : (
                      <span className="flex flex-col items-center gap-2 text-[11px] text-[var(--text-faint)]">
                        {j.status === 'running' && <Loader2 size={16} className="animate-spin" />}
                        {j.status === 'running'
                          ? (j.total_steps ? `Step ${j.step}/${j.total_steps}` : 'Starting…')
                          : 'Waiting its turn'}
                      </span>
                    )}
                    <span className="absolute left-2 top-2 text-[10px] px-1.5 py-0.5 rounded-md bg-black/50 text-white/80 tabular-nums">
                      {j.label}
                    </span>
                  </button>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-[var(--text-faint)] text-center">
                {running
                  ? `Making ${batch.length} images, one after another. Choose one to save it or keep it as a character.`
                  : 'Choose an image to save it or keep it as a character.'}
              </p>
            </div>
          ) : imageUrl ? (
            <div className="flex flex-col items-center gap-2 max-h-full min-h-0">
              {batch.length > 1 && (
                <button onClick={() => setFocus(null)}
                        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg text-[var(--text-dim)] hover:text-white hover:bg-[var(--bg-raised)] transition">
                  <LayoutGrid size={13} /> All {batch.length} images{job?.seed != null ? ` · this one is seed ${job.seed}` : ''}
                </button>
              )}
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
                onDiscarded={() => job && forget(job.id)}
              />
            </div>
          ) : running && current ? (
            <div className="flex flex-col items-center gap-3 text-[var(--text-dim)]">
              <Loader2 size={22} className="animate-spin" />
              <span className="text-sm">
                {current.total_steps ? `Generating — step ${current.step}/${current.total_steps}` : 'Generating…'}
              </span>
              {model?.engine === 'mflux' && (
                <span className="text-[11px] text-[var(--text-faint)]">
                  {current.step > 0
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
                  {current.step > 0
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
                className="w-8 h-8 max-md:w-11 max-md:h-11 rounded-full btn-accent flex items-center justify-center disabled:opacity-30 transition shrink-0"
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
        <div className="w-64 shrink-0 border-l border-[var(--border-soft)] p-4 overflow-y-auto flex flex-col gap-4
                        max-md:fixed max-md:inset-0 max-md:z-40 max-md:w-auto max-md:border-0
                        max-md:bg-[var(--bg)] max-md:pt-[calc(1rem+env(safe-area-inset-top))]
                        max-md:pb-[calc(1rem+env(safe-area-inset-bottom))]">
          <div className="flex items-center justify-between">
            <h3 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Generation options</h3>
            <button onClick={() => setOptionsOpen(false)}
                    className="md:hidden min-h-11 px-4 rounded-lg bg-[var(--bg-raised)] text-sm">
              Done
            </button>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-[var(--text-dim)]">Images</span>
            <div className="flex gap-1">
              {[1, 2, 4, 6, 8].map((n) => (
                <button key={n} onClick={() => setCount(n)}
                        className={`flex-1 text-xs py-1.5 rounded-lg tabular-nums transition ${
                          count === n ? 'bg-[var(--bg-raised)] text-white' : 'card text-[var(--text-faint)] hover:text-[var(--text-dim)]'}`}>
                  {n}
                </button>
              ))}
            </div>
            {count > 1 && (
              <span className="text-[10px] text-[var(--text-faint)] leading-snug">
                Made one after another on consecutive seeds{seed ? ` from ${seed}` : ''}, so each can be made again.
              </span>
            )}
          </div>

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
