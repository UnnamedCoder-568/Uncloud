/**
 * Adding a model from anywhere on disk.
 *
 * Three screens, in the order a person needs them: choose a file or folder;
 * see what it is, what it is missing and whether it will run — before anything
 * is written; then what was written. Every conclusion shows where it came
 * from, because "Uncloud thinks this is Wan" is only worth trusting if the
 * reason is one click away.
 */

import { useState } from 'react';
import { libraryChanged } from '../lib/library-changed';
import { open } from '@tauri-apps/plugin-dialog';
import {
  AlertTriangle, Check, CheckCircle2, ChevronRight, File, Folder, Loader2, X, XCircle,
} from 'lucide-react';
import { importModel, inspectModel } from '../lib/sidecar';
import type { MetadataStep, ModelImportResult, ModelInspection } from '../lib/sidecar';
import { formatBytes } from '../lib/format';

const TASKS: Record<string, string> = {
  'text-generation': 'Text', 'image-generation': 'Image', 'video-generation': 'Video',
  'text-encoder': 'Text encoder', 'speech-to-text': 'Speech to text',
  'text-to-speech': 'Text to speech', 'music-generation': 'Music',
  'pipeline-component': 'Pipeline part', adapter: 'Adapter', unknown: 'Unknown',
};

const CONFIDENCE: Record<string, { label: string; tone: string; hint: string }> = {
  certain: { label: 'Certain', tone: 'text-emerald-400',
             hint: 'The files declare it.' },
  inferred: { label: 'Inferred', tone: 'text-sky-300',
              hint: 'Worked out from the structure of the files.' },
  guessed: { label: 'Guessed', tone: 'text-amber-400',
             hint: 'Only the name suggests it.' },
  unknown: { label: 'Unknown', tone: 'text-rose-400',
             hint: 'Nothing in the files says what this is.' },
};

const MFLUX_BASES: Record<string, string> = {
  flux2_klein_4b: 'FLUX.2 Klein 4B', flux2_klein_9b: 'FLUX.2 Klein 9B',
  z_image_turbo: 'Z-Image Turbo', krea2: 'Krea 2',
};

function stepLabel(step: MetadataStep): string {
  switch (step.action) {
    case 'present': return 'Already there';
    case 'create': return `Will be created from ${step.source}`;
    case 'copy': return `Will be copied from ${step.source}`;
    case 'fetch': return `Will be downloaded from ${step.source}`;
    case 'choose': return 'Needs you to choose';
    default: return 'Cannot be created here';
  }
}

/** The sentence inside an engine error, not the raw status line. */
function explain(error: unknown): string {
  const text = String(error);
  const json = text.slice(text.indexOf('{'));
  try {
    const body = JSON.parse(json);
    const denied = body?.detail?.denied;
    if (denied) {
      return denied.category === 'network'
        ? 'Your permission settings do not allow network access, so the online lookup was refused. Change it in Settings, or add the model without looking anything up.'
        : `Refused by your permission settings: ${denied.reason || denied.action}.`;
    }
    if (typeof body?.detail === 'string') return body.detail;
  } catch { /* not JSON: fall through */ }
  return text;
}

export default function AddModel({ onClose, onAdded }: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const [inspection, setInspection] = useState<ModelInspection | null>(null);
  const [name, setName] = useState('');
  const [family, setFamily] = useState('');
  const [online, setOnline] = useState(false);
  const [licence, setLicence] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ModelImportResult | null>(null);

  async function inspect(path: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const found = await inspectModel(path);
      setInspection(found);
      setName(found.identification.name);
      setFamily('');
      setOnline(false);
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusy(false);
    }
  }

  async function choose(directory: boolean) {
    const picked = await open(directory
      ? { directory: true, multiple: false, title: 'Choose a model folder' }
      : { multiple: false, title: 'Choose a model file',
          filters: [{ name: 'Model weights', extensions: ['gguf', 'safetensors'] }] });
    if (typeof picked === 'string') await inspect(picked);
  }

  async function add() {
    if (!inspection) return;
    setBusy(true);
    setError(null);
    try {
      const result = await importModel({
        path: inspection.identification.path, name: name.trim(), family,
        online, licence: licence.trim() || 'unknown',
      });
      setDone(result);
      onAdded();
      // Every view that lists models refreshes, not just the one that asked.
      libraryChanged();
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusy(false);
    }
  }

  const id = inspection?.identification;
  const verdict = inspection?.verdict;
  const confidence = CONFIDENCE[id?.confidence ?? 'unknown'];
  const needsChoice = inspection?.plan.some((s) => s.action === 'choose') && !family;
  const lookupHelps = inspection?.plan.some((s) => s.action === 'unavailable' || s.caution);
  const isContainer = !!id?.contents.length && id.layout === 'unknown';
  // Components waiting only for an index the plan is about to write will run
  // once it is written; saying "cannot load" before the button is pressed
  // contradicts the screen that follows it.
  const indexOnTheWay = !!verdict && !verdict.runnable && verdict.note.includes('model_index.json')
    && !!inspection?.plan.some((s) => s.file === 'model_index.json'
                                     && ['create', 'copy', 'fetch'].includes(s.action));
  const willRun = !!verdict && (verdict.runnable || indexOnTheWay);

  return (
    <div className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-8 bg-black/50 backdrop-blur-sm"
         onClick={onClose}>
      <div className="modal-panel card w-full max-w-2xl max-h-[86vh] flex flex-col p-0"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-[var(--border-soft)]">
          <h2 className="text-sm">Add a model from disk</h2>
          <button className="tb-btn" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>

        <div className="overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {!inspection && !busy && (
            <>
              <p className="text-[12px] text-[var(--text-dim)] leading-relaxed">
                Point at a model you downloaded yourself. Uncloud reads what the files say
                about themselves — not their names — and shows you what it found before
                writing anything.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button onClick={() => choose(true)}
                        className="card p-4 text-left hover:border-[var(--border-strong)] transition flex items-start gap-3 max-md:min-h-11">
                  <Folder size={18} className="text-[var(--text-dim)] mt-0.5 shrink-0" />
                  <span>
                    <span className="text-sm block">A folder</span>
                    <span className="text-[11px] text-[var(--text-faint)]">A diffusers pipeline, an MLX checkpoint, a voice model</span>
                  </span>
                </button>
                <button onClick={() => choose(false)}
                        className="card p-4 text-left hover:border-[var(--border-strong)] transition flex items-start gap-3 max-md:min-h-11">
                  <File size={18} className="text-[var(--text-dim)] mt-0.5 shrink-0" />
                  <span>
                    <span className="text-sm block">A single file</span>
                    <span className="text-[11px] text-[var(--text-faint)]">A .gguf or .safetensors</span>
                  </span>
                </button>
              </div>
            </>
          )}

          {busy && !done && (
            <p className="text-[12px] text-[var(--text-faint)] flex items-center gap-2">
              <Loader2 size={13} className="animate-spin" /> Reading the files…
            </p>
          )}

          {id && verdict && !done && !busy && (
            <>
              <div className="font-mono text-[11px] text-[var(--text-faint)] break-all">{id.path}</div>

              {isContainer ? (
                <div className="flex flex-col gap-2">
                  <p className="text-[12px] text-[var(--text-dim)]">
                    This folder holds models rather than being one. Choose which to add:
                  </p>
                  {id.contents.map((c) => (
                    <button key={c.path} onClick={() => inspect(c.path)}
                            className="card p-3 text-left flex items-center justify-between gap-3 hover:border-[var(--border-strong)] transition max-md:min-h-11">
                      <span className="min-w-0">
                        <span className="text-sm block truncate">{c.name}</span>
                        <span className="text-[11px] text-[var(--text-faint)]">{TASKS[c.task] ?? c.task}{c.family ? ` · ${c.family}` : ''}</span>
                      </span>
                      <ChevronRight size={14} className="text-[var(--text-faint)] shrink-0" />
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  <label className="flex flex-col gap-1.5">
                    <span className="text-xs text-[var(--text-dim)]">Name in the library</span>
                    <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120}
                           className="card px-3 py-2 text-sm bg-transparent outline-none focus:border-[var(--border-strong)]" />
                  </label>

                  <div className="flex flex-wrap items-center gap-2 text-[11px]">
                    <span className="px-2 py-0.5 rounded bg-[var(--bg-inset)]">{TASKS[id.task] ?? id.task}</span>
                    {id.family && <span className="px-2 py-0.5 rounded bg-[var(--bg-inset)] font-mono">{id.family}</span>}
                    {id.pipeline && <span className="px-2 py-0.5 rounded bg-[var(--bg-inset)] font-mono">{id.pipeline}</span>}
                    {id.quantization && <span className="px-2 py-0.5 rounded bg-[var(--bg-inset)] font-mono">{id.quantization}</span>}
                    {id.size_bytes > 0 && <span className="text-[var(--text-faint)]">{formatBytes(id.size_bytes)}</span>}
                    <span className={`ml-auto ${confidence.tone}`} title={confidence.hint}>{confidence.label}</span>
                  </div>

                  <div className={`card p-3 flex items-start gap-2.5 text-[12px] ${willRun ? '' : 'border-amber-500/30'}`}>
                    {willRun
                      ? <CheckCircle2 size={15} className="text-emerald-400 shrink-0 mt-0.5" />
                      : <AlertTriangle size={15} className="text-amber-400 shrink-0 mt-0.5" />}
                    <span className="text-[var(--text-dim)] leading-relaxed">
                      {indexOnTheWay
                        ? `Uncloud can run this with its ${verdict.engine} engine once model_index.json is written below.`
                        : verdict.runnable
                        ? `Uncloud can run this with its ${verdict.engine} engine.`
                        : verdict.note || 'Uncloud cannot run this yet. It will still be listed, with the reason.'}
                    </span>
                  </div>

                  {id.candidates.length > 0 && id.layout === 'mflux-checkpoint' && (
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs text-[var(--text-dim)]">Which base model was this cut from?</span>
                      <select value={family} onChange={(e) => setFamily(e.target.value)}
                              className="card px-3 py-2 text-sm bg-transparent outline-none max-md:min-h-11">
                        <option value="">Choose…</option>
                        {id.candidates.map((c) => <option key={c} value={c}>{MFLUX_BASES[c] ?? c}</option>)}
                      </select>
                      <span className="text-[11px] text-[var(--text-faint)]">
                        The checkpoint does not record it and its tensors do not settle it. The wrong base fails on load, so this is asked rather than guessed.
                      </span>
                    </label>
                  )}

                  {inspection.plan.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-xs text-[var(--text-dim)]">Files it needs</span>
                      {inspection.plan.map((step) => (
                        <div key={step.file} className="text-[11.5px] flex flex-col gap-0.5 py-1.5 border-t border-[var(--border-soft)] first:border-t-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono">{step.file}</span>
                            <span className={step.action === 'unavailable' ? 'text-rose-400'
                              : step.caution || step.action === 'choose' ? 'text-amber-400' : 'text-[var(--text-faint)]'}>
                              {stepLabel(step)}
                            </span>
                          </div>
                          {step.detail && <span className="text-[var(--text-faint)] leading-relaxed">{step.detail}</span>}
                        </div>
                      ))}
                      <span className="text-[11px] text-[var(--text-faint)]">
                        Nothing already there is ever replaced. Created files are marked as created, and uncloud-model.json records what was found.
                      </span>
                    </div>
                  )}

                  {lookupHelps && (
                    <label className="flex items-start gap-2.5 text-[12px] cursor-pointer max-md:min-h-11">
                      <input type="checkbox" checked={online} onChange={(e) => setOnline(e.target.checked)}
                             disabled={!id.base_repo} className="mt-0.5" />
                      <span className="text-[var(--text-dim)]">
                        Look up missing configuration on huggingface.co
                        <span className="block text-[11px] text-[var(--text-faint)]">
                          {id.base_repo
                            ? `From ${id.base_repo}. Configuration files only — never weights — and never past a repository's gate.`
                            : 'Not possible here: nothing in these files names the repository they came from.'}
                        </span>
                      </span>
                    </label>
                  )}

                  <label className="flex flex-col gap-1.5">
                    <span className="text-xs text-[var(--text-dim)]">Licence <span className="text-[var(--text-faint)]">(optional)</span></span>
                    <input value={licence} onChange={(e) => setLicence(e.target.value)} maxLength={80}
                           placeholder="Leave blank if you do not know"
                           className="card px-3 py-2 text-sm bg-transparent outline-none focus:border-[var(--border-strong)]" />
                    {id.licence_claim && (
                      <span className="text-[11px] text-[var(--text-faint)]">
                        The model card says <span className="font-mono">{id.licence_claim}</span>. That is a claim, not a verification — check the publisher's terms before relying on it.
                      </span>
                    )}
                  </label>

                  {(id.warnings.length > 0 || id.evidence.length > 0) && (
                    <details className="text-[11.5px]">
                      <summary className="cursor-pointer text-[var(--text-dim)] max-md:min-h-11 flex items-center">How this was worked out</summary>
                      <ul className="mt-2 flex flex-col gap-1">
                        {id.warnings.map((w) => (
                          <li key={w} className="text-amber-400/90 flex gap-1.5"><AlertTriangle size={11} className="mt-0.5 shrink-0" />{w}</li>
                        ))}
                        {id.evidence.map((e, i) => (
                          <li key={i} className="text-[var(--text-faint)]"><span className="font-mono text-[var(--text-dim)]">{e.source}</span> — {e.finding}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
            </>
          )}

          {done && (
            <div className="flex flex-col gap-3 text-[12px]">
              <div className="flex items-start gap-2.5">
                {done.verdict.runnable
                  ? <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
                  : <AlertTriangle size={16} className="text-amber-400 shrink-0" />}
                <span className="text-[var(--text-dim)]">
                  <strong className="text-white">{done.model.name}</strong> is in your library
                  {done.verdict.runnable ? ' and ready to use.' : `, but cannot run yet: ${done.verdict.note}`}
                </span>
              </div>
              {done.result.created.map((f) => (
                <span key={f} className="flex items-center gap-1.5 text-[var(--text-faint)]"><Check size={12} className="text-emerald-400" /> Created <span className="font-mono">{f}</span></span>
              ))}
              {done.result.skipped.map((f) => (
                <span key={f} className="text-[var(--text-faint)]">Left <span className="font-mono">{f}</span> as it was — it appeared before it could be written.</span>
              ))}
              {done.result.failed.map((f) => (
                <span key={f.file} className="flex items-center gap-1.5 text-rose-400"><XCircle size={12} /> Could not write {f.file}: {f.error}</span>
              ))}
            </div>
          )}

          {error && <p className="text-[12px] text-rose-400 leading-relaxed">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--border-soft)]">
          {inspection && !done && (
            <button onClick={() => { setInspection(null); setError(null); }}
                    className="text-xs px-3 py-1.5 rounded-lg text-[var(--text-dim)] hover:text-white transition mr-auto max-md:min-h-11">
              Choose another
            </button>
          )}
          <button onClick={onClose}
                  className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition max-md:min-h-11">
            {done ? 'Done' : 'Cancel'}
          </button>
          {inspection && !done && !isContainer && (
            <button onClick={add} disabled={busy || needsChoice}
                    className="btn-accent text-xs px-3 py-1.5 rounded-lg disabled:opacity-40 flex items-center gap-1.5 max-md:min-h-11">
              {busy && <Loader2 size={12} className="animate-spin" />} Add to library
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
