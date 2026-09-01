import { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { Check, Download, FolderCog, HardDrive, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { getCatalog, getLibrary, startDownload, listDownloads, getSettings, setModelsDir as saveModelsDir } from '../lib/sidecar';
import type { CatalogEntry, LocalModel, DownloadState } from '../lib/sidecar';
import { formatBytes, formatSpeed } from '../lib/format';

const CATEGORIES: { id: string; label: string }[] = [
  { id: 'text', label: 'Text' },
  { id: 'image', label: 'Image' },
  { id: 'video', label: 'Video' },
  { id: 'voice-stt', label: 'Speech-to-Text' },
  { id: 'voice-tts', label: 'Text-to-Speech' },
];

export default function ModelsView() {
  const [category, setCategory] = useState('text');
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [library, setLibrary] = useState<LocalModel[]>([]);
  const [downloads, setDownloads] = useState<DownloadState[]>([]);
  const [onlyUncensored, setOnlyUncensored] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Where downloads land. Picking a folder stages it; nothing moves until Save,
  // so a mis-click in the file dialog cannot silently redirect the next 20GB.
  const [modelsDir, setModelsDir] = useState('');
  const [pendingDir, setPendingDir] = useState<string | null>(null);
  const [dirSaved, setDirSaved] = useState(false);

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
        <h1 className="text-2xl font-semibold mb-4">Models</h1>
        <div className="flex items-center justify-between">
          <div className="flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg">
            {CATEGORIES.map((c) => (
              <button
                key={c.id}
                onClick={() => setCategory(c.id)}
                className={`px-3 py-1.5 rounded-md text-xs transition ${
                  category === c.id ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
          {category === 'text' && (
            <label className="flex items-center gap-2 text-xs text-[var(--text-dim)] cursor-pointer select-none">
              <input type="checkbox" checked={onlyUncensored} onChange={(e) => setOnlyUncensored(e.target.checked)} />
              Uncensored only
            </label>
          )}
        </div>
      </header>

      <div className="px-6 py-5">
        <section className="card p-4 mb-8 flex items-center gap-3">
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
            {pendingDir && (
              <div className="text-[11px] text-amber-400/80 mt-1">
                Not saved yet — press Save to download here from now on.
              </div>
            )}
          </div>
          <button
            onClick={chooseDir}
            className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition shrink-0"
          >
            Change…
          </button>
          <button
            onClick={saveDir}
            disabled={!pendingDir}
            className="btn-accent text-xs px-3 py-1.5 rounded-lg shrink-0 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {dirSaved ? <><Check size={13} /> Saved</> : 'Save'}
          </button>
        </section>

        {filteredLocal.length > 0 && (
          <section className="mb-8">
            <h2 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)] mb-3">
              Installed
            </h2>
            <div className="grid grid-cols-2 gap-3">
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
                    {m.note && <div className="text-[11px] text-amber-400/80 mt-1">{m.note}</div>}
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
          <div className="grid grid-cols-2 gap-3">
            {filteredCatalog.map((entry) => {
              const active = activeDownloadFor(entry.id);
              const done = downloads.find((d) => d.catalog_id === entry.id && d.status === 'done');
              return (
                <div key={entry.id} className="card p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm">{entry.name}</div>
                      <div className="text-[11px] text-[var(--text-faint)] mt-0.5">{entry.description}</div>
                    </div>
                    <div className="flex flex-wrap gap-1 justify-end shrink-0">
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
                  </div>

                  <div className="flex items-center justify-between mt-3">
                    <span className="text-[11px] font-mono text-[var(--text-faint)]">
                      {entry.size_gb.toFixed(1)} GB{entry.context_length ? ` · ${(entry.context_length / 1000).toFixed(0)}k ctx` : ''}
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
    </div>
  );
}
