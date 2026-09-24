import ActivityOrb from '../components/ActivityOrb';
import { useCallback, useEffect, useRef, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { FolderOpen, Trash2, RefreshCw, FolderCog } from 'lucide-react';
import { listOutputs, outputBlobUrl, revealOutput, deleteOutput, setOutputDir } from '../lib/sidecar';
import type { OutputFile } from '../lib/sidecar';
import { formatBytes } from '../lib/format';
import { onWake } from '../lib/awake';
import { inDesktop } from '../lib/platform';

const FILTERS = [
  { id: '', label: 'Everything' },
  { id: 'image', label: 'Images' },
  { id: 'video', label: 'Video' },
  { id: 'audio', label: 'Audio' },
];

function ago(seconds: number): string {
  if (seconds < 90) return 'just now';
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/** Thumbnails are fetched through the token-authenticated endpoint, so each one
 *  becomes a blob URL. Revoked on unmount, or the tab leaks memory as it fills. */
function Thumb({ file }: { file: OutputFile }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let dead = false;
    let made: string | null = null;
    if (file.kind === 'image' || file.kind === 'video') {
      outputBlobUrl(file.path)
        .then((u) => { if (dead) URL.revokeObjectURL(u); else { made = u; setUrl(u); } })
        .catch(() => undefined);
    }
    return () => { dead = true; if (made) URL.revokeObjectURL(made); };
  }, [file.path, file.kind]);

  if (file.kind === 'video') {
    return url
      ? <video src={url} muted loop playsInline className="w-full h-full object-cover"
               onMouseEnter={(e) => void e.currentTarget.play()}
               onMouseLeave={(e) => e.currentTarget.pause()} />
      : <div className="w-full h-full bg-[var(--bg-inset)]" />;
  }
  if (file.kind === 'image') {
    return url
      ? <img src={url} alt={file.name} className="w-full h-full object-cover" />
      : <div className="w-full h-full bg-[var(--bg-inset)]" />;
  }
  return (
    <div className="w-full h-full bg-[var(--bg-inset)] flex items-center justify-center">
      <span className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">
        {file.name.split('.').pop()}
      </span>
    </div>
  );
}

export default function OutputsView() {
  const [files, setFiles] = useState<OutputFile[]>([]);
  const [root, setRoot] = useState('');
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const seen = useRef(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listOutputs(filter);
      setFiles(r.files);
      setRoot(r.root);
      seen.current = r.files.length;
      setError(null);
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ''));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { refresh(); }, [refresh]);

  // Cheap poll so work finished in another tab turns up here without a reload.
  useEffect(() => {
    const look = async () => {
      const r = await listOutputs(filter).catch(() => null);
      if (r && r.files.length !== seen.current) {
        seen.current = r.files.length;
        setFiles(r.files);
      }
    };
    const t = setInterval(() => { void look(); }, 5000);
    // Coming back to the page: everything finished while it was away landed in
    // this folder, and waiting five seconds to say so reads as an empty gallery.
    const wake = onWake(() => { void look(); });
    return () => { clearInterval(t); wake(); };
  }, [filter]);

  async function remove(f: OutputFile) {
    if (!confirm(`Delete ${f.name}? This cannot be undone.`)) return;
    await deleteOutput(f.path).catch(() => undefined);
    refresh();
  }

  // The folder is shown here, so it should be changeable here — sending someone
  // to Settings to act on what they are already looking at is a detour.
  async function changeFolder() {
    const picked = await open({ directory: true, multiple: false, defaultPath: root || undefined });
    if (typeof picked !== 'string' || !picked || picked === root) return;
    await setOutputDir(picked);
    refresh();
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="px-6 py-5">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold">Outputs</h1>
            <button
              onClick={changeFolder}
              disabled={!inDesktop()}
              title={inDesktop() ? 'Choose where generated work is saved'
                                 : 'Changed on the computer running Uncloud'}
              className="flex items-center gap-1.5 text-[11px] text-[var(--text-faint)] font-mono mt-1 max-w-full truncate hover:text-[var(--text-dim)] transition"
            >
              <FolderCog size={11} className="shrink-0" />
              <span className="truncate">{root}</span>
            </button>
            {root.includes('/.uncloud/outputs') && (
              <p className="text-[11px] text-amber-400/80 mt-1">
                {inDesktop()
                  ? "Still the default hidden folder — click the path to pick somewhere you'll open."
                  : 'Still the default hidden folder. Choose another on the computer running Uncloud.'}
              </p>
            )}
          </div>
          <button
            onClick={refresh}
            className="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition shrink-0"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>

        <div className="flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg w-fit mb-5">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`text-[11px] px-3 py-1.5 rounded-md transition ${
                filter === f.id ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="card p-4 mb-5 border-rose-500/30">
            <p className="text-[11px] text-rose-400">{error}</p>
          </div>
        )}

        {loading && files.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-dim)] py-10 justify-center">
            <ActivityOrb state="working" size={20} label="Working…" /> Loading
          </div>
        ) : files.length === 0 ? (
          <p className="text-sm text-[var(--text-faint)] py-10 text-center">
            Nothing generated yet. Anything you make in Image, Video, Music or Voice
            lands here.
          </p>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-3">
            {files.map((f) => (
              <div key={f.path} className="card overflow-hidden group">
                <div className="aspect-square bg-[var(--bg-inset)] overflow-hidden">
                  <Thumb file={f} />
                </div>
                <div className="p-2.5">
                  <div className="text-[11px] truncate" title={f.relative}>{f.name}</div>
                  <div className="text-[10px] text-[var(--text-faint)] mt-0.5">
                    {formatBytes(f.size_bytes)} · {ago(f.age_seconds)}
                  </div>
                  <div className="flex gap-1 mt-2">
                    <button
                      onClick={() => revealOutput(f.path)}
                      title="Show in Finder"
                      className="flex-1 flex items-center justify-center gap-1 text-[10px] py-1.5 rounded-md bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition"
                    >
                      <FolderOpen size={11} /> Reveal
                    </button>
                    <button
                      onClick={() => remove(f)}
                      title="Delete"
                      className="px-2 py-1.5 rounded-md bg-[var(--bg-inset)] text-[var(--text-faint)] hover:text-rose-400 transition"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
