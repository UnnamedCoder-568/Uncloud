import { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import {
  ArrowUpRight, Check, Download, FolderCog, HardDrive, Loader2, CheckCircle2, XCircle,
} from 'lucide-react';
import { forgetModel, getCatalog, getLibrary, startDownload, listDownloads, getSettings, setModelsDir as saveModelsDir,
         acknowledgeModelLicence, getModelLicence, type ModelLicence } from '../lib/sidecar';
import type { CatalogEntry, LocalModel, DownloadState } from '../lib/sidecar';
import { formatBytes, formatSpeed } from '../lib/format';
import OnTheComputer from '../components/OnTheComputer';
import AddModel from '../components/AddModel';
import { inDesktop } from '../lib/platform';
import { openExternal } from '../lib/links';
import ModelHubs from '../components/ModelHubs';

const CATEGORIES: { id: string; label: string }[] = [
  { id: 'text', label: 'Text' },
  { id: 'image', label: 'Image' },
  { id: 'video', label: 'Video' },
  { id: 'voice-stt', label: 'Speech-to-Text' },
  { id: 'voice-tts', label: 'Text-to-Speech' },
];

export default function ModelsLibrary() {
  const [category, setCategory] = useState('text');
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [library, setLibrary] = useState<LocalModel[]>([]);
  const [downloads, setDownloads] = useState<DownloadState[]>([]);
  const [onlyUncensored, setOnlyUncensored] = useState(false);
  const [disclosing, setDisclosing] = useState<
    { terms: ModelLicence; entry: CatalogEntry } | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Where downloads land. Picking a folder stages it; nothing moves until Save,
  // so a mis-click in the file dialog cannot silently redirect the next 20GB.
  const [modelsDir, setModelsDir] = useState('');
  const [pendingDir, setPendingDir] = useState<string | null>(null);
  const [dirSaved, setDirSaved] = useState(false);
  const [adding, setAdding] = useState(false);

  async function chooseDir() {
    const picked = await open({ directory: true, multiple: false, defaultPath: modelsDir || undefined });
    if (typeof picked === 'string' && picked && picked !== modelsDir) setPendingDir(picked);
  }

  async function saveDir() {
    if (!pendingDir) return;
    await saveModelsDir(pendingDir);
    setModelsDir(pendingDir);
    setPendingDir(null);
    setDirSaved(true);
    setTimeout(() => setDirSaved(false), 2500);
    refresh();
  }

  /**
   * Each source is fetched independently. Previously all three went through a
   * single Promise.all with no catch, so one failing call left every list empty
   * and the page rendered as a blank grid with nothing explaining why.
   */
  async function refresh() {
    setLoading(true);
    const problems: string[] = [];

    const [c, l, d, cfg] = await Promise.all([
      getCatalog().catch((e) => { problems.push(`catalog: ${e}`); return null; }),
      getLibrary().catch((e) => { problems.push(`installed models: ${e}`); return null; }),
      listDownloads().catch((e) => { problems.push(`downloads: ${e}`); return null; }),
      getSettings().catch(() => null),
    ]);

    // This view stays mounted, and the same folder is editable from Settings —
    // reread it rather than trusting what was fetched when the app started.
    if (cfg) setModelsDir(cfg.models_dir);
    if (c) setCatalog(c);
    if (l) setLibrary(l);
    if (d) setDownloads(d);
    setError(problems.length ? problems.join('\n') : null);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
    const t = setInterval(async () => {
      const d = await listDownloads().catch(() => null);
      if (d) setDownloads(d);
    }, 1200);
    return () => clearInterval(t);
  }, []);

  const activeDownloadFor = (catalogId: string) =>
    downloads.find((d) => d.catalog_id === catalogId && (d.status === 'downloading' || d.status === 'pending'));

  async function download(entry: CatalogEntry) {
    // Terms first, and only where there is something worth saying. Asked at
    // this moment rather than for every card on render: thirty-three models
    // would be thirty-three requests to answer a question almost nobody asks.
    //
    // Nothing here can refuse. Most of this catalogue's licences have never
    // been read, and "nobody checked" is not grounds to stop somebody
    // installing a model — it is grounds to say so, once.
    let terms: ModelLicence | null = null;
    try { terms = await getModelLicence(entry.id); } catch { /* shown below */ }
    if (terms?.needs_acknowledgement) {
      setDisclosing({ terms, entry });
      return;
    }
    await startDownload(entry.id);
    refresh();
  }

  async function acknowledgeAndDownload() {
    if (!disclosing) return;
    const { entry } = disclosing;
    setDisclosing(null);
    await acknowledgeModelLicence(entry.id);
    await startDownload(entry.id);
    refresh();
  }

  const filteredCatalog = catalog
    .filter((e) => e.category === category)
    .filter((e) => !onlyUncensored || e.tags.includes('uncensored'));
  const filteredLocal = library.filter((m) => m.category === category);

  return (
    <div className="h-full overflow-y-auto">
      <header className="sticky top-0 bg-[var(--bg)]/90 backdrop-blur border-b border-[var(--border-soft)] px-6 pt-5 pb-3 z-10">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg max-md:w-full max-md:overflow-x-auto">
            {CATEGORIES.map((c) => (
              <button
                key={c.id}
                onClick={() => setCategory(c.id)}
                className={`px-3 py-1.5 rounded-md text-xs transition whitespace-nowrap max-md:min-h-11 ${
                  category === c.id ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
          {category === 'text' && (
            <label className="flex items-center gap-2 text-xs text-[var(--text-dim)] cursor-pointer select-none max-md:min-h-11">
              <input type="checkbox" checked={onlyUncensored} onChange={(e) => setOnlyUncensored(e.target.checked)} />
              Uncensored only
            </label>
          )}
        </div>
      </header>

      <div className="px-6 py-5">
        <section className="card p-4 mb-8 flex flex-wrap items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[var(--bg-inset)] flex items-center justify-center shrink-0">
            <FolderCog size={15} className="text-[var(--text-dim)]" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">
              Models are saved to
            </div>
            <div className="text-xs font-mono truncate mt-0.5" title={pendingDir ?? modelsDir}>
              {pendingDir ?? (modelsDir || 'Not set yet')}
            </div>
            {!inDesktop() && <div className="mt-1"><OnTheComputer /></div>}
            {pendingDir && (
              <div className="text-[11px] text-amber-400/80 mt-1">
                Not saved yet — press Save to download here from now on.
              </div>
            )}
          </div>
          {inDesktop() ? (
            <button
              onClick={chooseDir}
              className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition shrink-0"
            >
              Change…
            </button>
          ) : null}
          {inDesktop() && (
            <button
              onClick={() => setAdding(true)}
              className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition shrink-0"
              title="Add a model you downloaded yourself, from anywhere on disk"
            >
              Add from disk…
            </button>
          )}
          {inDesktop() && <button
            onClick={saveDir}
            disabled={!pendingDir}
            className="btn-accent text-xs px-3 py-1.5 rounded-lg shrink-0 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {dirSaved ? <><Check size={13} /> Saved</> : 'Save'}
          </button>}
        </section>

        {filteredLocal.length > 0 && (
          <section className="mb-8">
            <h2 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)] mb-3">
              Installed
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredLocal.map((m) => (
                <div key={m.id} className="card p-4 flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-[var(--bg-inset)] flex items-center justify-center shrink-0">
                    <HardDrive size={15} className="text-[var(--text-dim)]" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm truncate">{m.name}</div>
                    <div className="text-[11px] text-[var(--text-faint)] font-mono mt-0.5">
                      {m.engine.toUpperCase()} · {formatBytes(m.size_gb * 1024 ** 3)}
                    </div>
                    {m.note && <div className={`text-[11px] mt-1 ${m.ready ? 'text-[var(--text-faint)]' : 'text-amber-400/80'}`}>{m.note}</div>}
                    {m.tags?.includes('imported') && inDesktop() && (
                      <button
                        onClick={async () => { await forgetModel(m.path); refresh(); }}
                        className="text-[11px] text-[var(--text-faint)] hover:text-[var(--text-dim)] mt-1.5 max-md:min-h-11"
                        title="Stop listing it. Its files stay where they are."
                      >
                        Remove from library
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {error && (
          <div className="card p-4 mb-6 border-rose-500/30">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-rose-400">
                  <XCircle size={14} />
                  <span className="text-xs font-medium">Could not load everything</span>
                </div>
                <p className="mt-1.5 text-[11px] text-[var(--text-dim)] whitespace-pre-wrap leading-relaxed">
                  {error}
                </p>
              </div>
              <button
                onClick={refresh}
                className="text-[11px] px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition shrink-0"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {/* Above the catalogue rather than after it: the text list runs to two
            dozen entries, and a way out placed below them is a way out nobody
            scrolls far enough to find. */}
        <ModelHubs category={category} onAdd={() => setAdding(true)} />

        <section>
          <h2 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)] mb-3">Download</h2>
          {filteredCatalog.length === 0 && (
            <p className="text-[11px] text-[var(--text-faint)] py-6 text-center">
              {loading
                ? 'Loading…'
                : catalog.length === 0
                  ? 'The catalog could not be loaded.'
                  : onlyUncensored
                    ? 'No uncensored models in this category.'
                    : 'Nothing to download in this category.'}
            </p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {filteredCatalog.map((entry) => {
              const active = activeDownloadFor(entry.id);
              const done = downloads.find((d) => d.catalog_id === entry.id && d.status === 'done');
              return (
                <div key={entry.id} className="card p-4 flex flex-col">
                  {/* Name, then labels, then the description — each on its own
                      line. Side by side, the labels were shrink-0, so a card
                      with three of them left the description a column two
                      words wide. */}
                  <div className="text-sm">{entry.name}</div>
                  {entry.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {entry.tags.map((t) => (
                        <span
                          key={t}
                          className={`text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                            t === 'uncensored' ? 'bg-rose-950/60 text-rose-300' : 'bg-[var(--bg-inset)] text-[var(--text-faint)]'
                          }`}
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="text-[11px] text-[var(--text-faint)] mt-2 leading-relaxed flex-1">
                    {entry.description}
                  </p>

                  <div className="flex items-center justify-between gap-2 mt-3">
                    <span className="flex items-center gap-2 min-w-0 text-[11px] font-mono text-[var(--text-faint)]">
                      <span className="shrink-0">
                        {entry.size_gb.toFixed(1)} GB{entry.context_length ? ` · ${(entry.context_length / 1000).toFixed(0)}k ctx` : ''}
                      </span>
                      {/* The publisher's own page: its model card, its licence
                          as they wrote it, and every other file they ship. */}
                      {/^[\w.-]+\/[\w.-]+$/.test(entry.repo) && (
                        <button
                          type="button"
                          onClick={() => { void openExternal(`https://huggingface.co/${entry.repo}`); }}
                          title={`Open ${entry.repo} on Hugging Face`}
                          className="flex items-center gap-0.5 font-sans text-[var(--text-faint)] hover:text-[var(--text)] transition truncate"
                        >
                          Hugging Face <ArrowUpRight size={11} className="shrink-0" />
                        </button>
                      )}
                    </span>

                    {entry.installed || done ? (
                      <span className="flex items-center gap-1 text-[11px] text-emerald-400">
                        <CheckCircle2 size={13} /> Installed
                      </span>
                    ) : active ? (
                      <div className="flex items-center gap-2 text-[11px] text-[var(--text-dim)]">
                        <Loader2 size={13} className="animate-spin" />
                        {active.percent.toFixed(0)}%{active.speed_bytes_s > 0 ? ` · ${formatSpeed(active.speed_bytes_s)}` : ''}
                      </div>
                    ) : (
                      <button
                        onClick={() => download(entry)}
                        className="flex items-center gap-1.5 text-[11px] btn-accent px-3 py-1.5 rounded-full transition"
                      >
                        <Download size={12} /> Download
                      </button>
                    )}
                  </div>
                  {active && (
                    <div className="mt-2 h-1 rounded-full bg-[var(--bg-inset)] overflow-hidden">
                      <div
                        className="h-full accent-bar transition-[width] duration-300"
                        style={{ width: `${Math.max(2, active.percent)}%` }}
                      />
                    </div>
                  )}
                  {downloads.find((d) => d.catalog_id === entry.id && d.status === 'error') && (
                    <div className="flex items-center gap-1 text-[11px] text-rose-400 mt-2">
                      <XCircle size={12} /> {downloads.find((d) => d.catalog_id === entry.id)?.error}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {disclosing && (
        <LicenceDialog terms={disclosing.terms} name={disclosing.entry.name}
                       onCancel={() => setDisclosing(null)}
                       onAccept={acknowledgeAndDownload} />
      )}
      {adding && <AddModel onClose={() => setAdding(false)} onAdded={refresh} />}
    </div>
  );
}

/** What a publisher's licence says, before the download starts.
 *
 *  It cannot refuse. There is no path from this dialog to "you may not install
 *  this" — the only buttons are cancel and continue, and that is the point: a
 *  licence describes what may be done with the OUTPUT, which depends on facts
 *  about the user that this application does not have.
 */
function LicenceDialog({ terms, name, onCancel, onAccept }: {
  terms: ModelLicence; name: string; onCancel: () => void; onAccept: () => void;
}) {
  const unread = terms.commercial_use === 'unverified';
  return (
    <div className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-8
                    bg-black/50 backdrop-blur-sm" onClick={onCancel}>
      <div className="modal-panel card w-full max-w-xl flex flex-col gap-4 p-6"
           onClick={(e) => e.stopPropagation()}>
        <div>
          <h3 className="text-sm mb-1">{terms.headline}</h3>
          <p className="text-[11px] text-[var(--text-faint)]">
            {unread ? 'Applies to models Uncloud has not checked' : name}
            {terms.licence_name ? ` · ${terms.licence_name}` : ''}
          </p>
        </div>

        <p className="text-xs leading-relaxed text-[var(--text-dim)]">
          {terms.explanation}
        </p>

        {unread && (
          <p className="text-xs leading-relaxed text-[var(--text-dim)]">
            You are being asked this once, not for every model. Uncloud has read the
            licences of some of its catalogue and not others; where it has not, it
            says so rather than guessing. Before you use anything commercially,
            check the model's own licence.
          </p>
        )}

        {terms.conditions.length > 0 && (
          <ul className="flex flex-col gap-2 text-xs leading-relaxed
                         text-[var(--text-dim)] border-l-2 border-[var(--accent)] pl-3">
            {terms.conditions.map((c) => <li key={c}>{c}</li>)}
          </ul>
        )}

        {terms.mixed && (
          <div className="text-xs text-[var(--text-dim)]">
            <p className="mb-2">
              This pipeline is assembled from separately-licensed parts, and they do
              not all say the same thing. Every one of them applies.
            </p>
            <ul className="flex flex-col gap-1 font-mono text-[11px]">
              {terms.per_component.map((c) => (
                <li key={c.role + c.name}>{c.role}: {c.name} — {c.licence}</li>
              ))}
            </ul>
          </div>
        )}

        {terms.url && (
          <a href={terms.url} target="_blank" rel="noreferrer"
             className="text-[11px] text-[var(--accent)] hover:underline">
            Read the licence itself — it is the authority, and this is a summary.
          </a>
        )}

        <div className="flex items-center justify-end gap-2 pt-1">
          <button onClick={onCancel}
                  className="text-xs px-4 py-2 rounded-lg text-[var(--text-dim)]
                             hover:text-[var(--text)] transition">
            Cancel
          </button>
          <button onClick={onAccept}
                  className="text-xs px-4 py-2 rounded-lg btn-accent transition">
            I understand — download it
          </button>
        </div>
      </div>
    </div>
  );
}
