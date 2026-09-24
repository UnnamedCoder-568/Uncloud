import ActivityOrb from '../components/ActivityOrb';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ImagePlus, Sparkles, X, Check, FolderDown } from 'lucide-react';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import {
  exportImages,
  fetchImageBlob,
  fetchImageBlobUrl,
  generateProductShots,
  getImageJob,
  getLibrary,
  getProductCategories,
  listCharacters,
  stopImage,
  uploadImage,
} from '../lib/sidecar';
import Dictate from '../components/Dictate';
import AddFromDisk from '../components/AddFromDisk';
import { useLibraryVersion } from '../lib/library-changed';
import { onWake, remember, remembered } from '../lib/awake';
import type { LocalModel, ProductCategory, ImageJob, Character } from '../lib/sidecar';
import { SplitTabs, useSplit } from '../components/Split';
import { downloadBlob, inDesktop } from '../lib/platform';

interface Result {
  job: ImageJob;
  url: string | null;
}

//: The shots of the last press, kept where a reload can find them.
const REMEMBERED = 'uncloud.product.jobs';

export default function ProductStudio() {
  const libraryVersion = useLibraryVersion();
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [categoryId, setCategoryId] = useState('apparel');
  const [selectedShots, setSelectedShots] = useState<string[]>([]);

  const [refPath, setRefPath] = useState<string | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const [characters, setCharacters] = useState<Character[]>([]);
  const [characterSlug, setCharacterSlug] = useState('');
  const [modelDescription, setModelDescription] = useState('');
  const [background, setBackground] = useState('');
  const [extra, setExtra] = useState('');

  const [results, setResults] = useState<Result[]>([]);
  //: Only the moment between pressing and the engine answering. What happens
  //  after that is the shots' own business, and is read from them — a set of
  //  shots the page stopped watching is still being rendered.
  const [starting, setStarting] = useState(false);
  const running = starting || results.some((r) => !r.job.done);
  const fileInput = useRef<HTMLInputElement>(null);

  // The shots are watched through a ref by one loop, so that losing the page —
  // a phone discarding a background tab — costs nothing but the view. See
  // lib/awake.
  const resultsRef = useRef(results);
  useEffect(() => { resultsRef.current = results; }, [results]);

  useEffect(() => {
    let stopped = false;

    const sync = async () => {
      if (stopped) return;
      for (const { job, url } of resultsRef.current) {
        if (stopped) return;
        if (!job.done) {
          const updated = await getImageJob(job.id).catch(() => null);
          if (updated && !stopped) {
            setResults((rs) => rs.map((r) => (r.job.id === job.id ? { ...r, job: updated } : r)));
          }
          continue;
        }
        // Finished, but the picture never arrived: fetched again rather than
        // only at the moment it finished.
        if (!url && job.status === 'done') {
          const got = await fetchImageBlobUrl(job.id).catch(() => null);
          if (got && !stopped) {
            setResults((rs) => rs.map((r) => (r.job.id === job.id && !r.url ? { ...r, url: got } : r)));
          }
        }
      }
    };

    const t = setInterval(() => { void sync(); }, 1500);
    const wake = onWake(() => { void sync(); });
    return () => { stopped = true; clearInterval(t); wake(); };
  }, []);

  // Shots started before the page was put away or reloaded.
  useEffect(() => {
    const ids = remembered(REMEMBERED);
    if (!ids.length) return;
    let dead = false;
    void Promise.all(ids.map((id) => getImageJob(id).catch(() => null))).then((found) => {
      const jobs = found.filter((j): j is ImageJob => !!j);
      if (!dead && jobs.length) setResults(jobs.map((job) => ({ job, url: null })));
    });
    return () => { dead = true; };
  }, []);

  useEffect(() => {
    getLibrary().then((list) => {
      const editors = list.filter((m) => m.category === 'image' && m.ready && m.capabilities.includes('edit'));
      setModels(editors);
      setModel((p) => p ?? editors[0] ?? null);
    });
  }, [libraryVersion]);

  useEffect(() => {
    getProductCategories().then((c) => {
      setCategories(c);
      const first = c.find((x) => x.id === 'apparel') ?? c[0];
      if (first) {
        setCategoryId(first.id);
        setSelectedShots(first.shots.slice(0, 2).map((s) => s.id));
      }
    });
    listCharacters().then(setCharacters).catch(() => setCharacters([]));
  }, []);

  const category = useMemo(
    () => categories.find((c) => c.id === categoryId) ?? null,
    [categories, categoryId],
  );

  function pickCategory(id: string) {
    setCategoryId(id);
    const cat = categories.find((c) => c.id === id);
    setSelectedShots(cat ? cat.shots.slice(0, 2).map((s) => s.id) : []);
  }

  function toggleShot(id: string) {
    setSelectedShots((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    try {
      const path = await uploadImage(file);
      setRefPath(path);
      setRefPreview(URL.createObjectURL(file));
    } catch (e) {
      alert(`Upload failed: ${e}`);
    } finally {
      setUploading(false);
    }
  }

  function applyCharacter(slug: string) {
    setCharacterSlug(slug);
    const c = characters.find((x) => x.slug === slug);
    if (c?.description) setModelDescription(c.description);
  }

  async function run() {
    if (!model || !refPath || selectedShots.length === 0 || running) return;
    setStarting(true);
    setResults([]);
    try {
      const jobs = await generateProductShots({
        model_path: model.path,
        reference_path: refPath,
        category: categoryId,
        shots: selectedShots,
        catalog_id: model.catalog_id,
        model_description: modelDescription,
        background,
        extra,
      });
      setResults(jobs.map((job) => ({ job, url: null })));
      remember(REMEMBERED, jobs.map((j) => j.id));
    } catch (e) {
      alert(`Generation failed: ${e}`);
    } finally {
      setStarting(false);
    }
  }

  async function exportAll() {
    const finished = results.filter((r) => r.job.status === 'done').map((r) => r.job.id);
    if (finished.length === 0) return;
    if (!inDesktop()) {
      // One after another rather than all at once: mobile browsers quietly
      // drop a burst of simultaneous downloads after the first.
      for (const [i, id] of finished.entries()) {
        downloadBlob(await fetchImageBlob(id), `product-shot-${i + 1}.png`);
        await new Promise((r) => setTimeout(r, 400));
      }
      return;
    }
    const dir = await openDialog({ directory: true, multiple: false, title: 'Export product shots to…' });
    if (typeof dir !== 'string') return;
    try {
      const res = await exportImages(finished, dir);
      alert(`Exported ${res.written.length} image${res.written.length === 1 ? '' : 's'} to ${res.dir}`);
    } catch (e) {
      alert(`Export failed: ${e}`);
    }
  }

  const canRun = !!model && !!refPath && selectedShots.length > 0 && !running;
  const doneCount = results.filter((r) => r.job.status === 'done').length;

  const split = useSplit(running);

  return (
    <div className="h-full flex split">
      <SplitTabs split={split} labels={['Shots', 'Results']} />
      {/* ---------------------------------------------------------- controls */}
      <div className={`w-[320px] shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5 split-pane${split.on(0)}`}>
        {/* model */}
        <div className="relative">
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Model</label>
          <button
            onClick={() => setPickerOpen((v) => !v)}
            className="mt-1.5 w-full flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-[var(--bg-inset)] hover:bg-[var(--bg-inset)]/70 transition"
          >
            <span className={model ? '' : 'text-[var(--text-faint)]'}>
              {model ? model.name : 'No reference-editing model'}
            </span>
            <ChevronDown size={13} className="text-[var(--text-faint)]" />
          </button>
          {pickerOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 card p-1.5 z-20 shadow-2xl">
              {models.length === 0 && (
                <div className="text-[11px] text-[var(--text-faint)] px-2 py-3 text-center">
                  Install FLUX.1 Kontext from the Models tab.
                </div>
              )}
              {models.map((m) => (
                <button
                  key={m.id}
                  onClick={() => { setModel(m); setPickerOpen(false); }}
                  className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition text-xs"
                >
                  {m.name}
                </button>
              ))}
              <div className="border-t border-[var(--border-soft)] mt-1 pt-1">
                <AddFromDisk onOpen={() => setPickerOpen(false)} />
              </div>
            </div>
          )}
        </div>

        {/* reference */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Product photo</label>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          {refPreview ? (
            <div className="mt-1.5 relative group">
              <img src={refPreview} alt="reference" className="w-full rounded-lg border border-[var(--border)]" />
              <button
                onClick={() => { setRefPath(null); setRefPreview(null); }}
                className="absolute top-2 right-2 w-6 h-6 rounded-full bg-black/70 flex items-center justify-center opacity-0 group-hover:opacity-100 touch:opacity-100 before:absolute before:-inset-2.5 before:content-[''] transition"
              >
                <X size={12} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
              className="mt-1.5 w-full h-28 rounded-lg border border-dashed border-[var(--border)] flex flex-col items-center justify-center gap-1.5 text-[var(--text-faint)] hover:border-[#3a3a42] hover:text-[var(--text-dim)] transition"
            >
              {uploading ? <ActivityOrb state="working" size={20} label="Working…" /> : <ImagePlus size={18} />}
              <span className="text-[11px]">{uploading ? 'Uploading…' : 'Add product photo'}</span>
            </button>
          )}
        </div>

        {/* category */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Category</label>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {categories.map((c) => (
              <button
                key={c.id}
                onClick={() => pickCategory(c.id)}
                title={c.description}
                className={`text-[11px] px-2.5 py-1.5 rounded-lg transition ${
                  categoryId === c.id
                    ? 'bg-[var(--bg-raised)] text-white border border-[var(--border)]'
                    : 'bg-[var(--bg-inset)] text-[var(--text-faint)] hover:text-[var(--text-dim)] border border-transparent'
                }`}
              >
                {c.name}
              </button>
            ))}
          </div>
        </div>

        {/* shots */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">
            Shots <span className="text-[var(--text-faint)]">({selectedShots.length})</span>
          </label>
          <div className="mt-1.5 flex flex-col gap-1">
            {category?.shots.map((s) => {
              const on = selectedShots.includes(s.id);
              return (
                <button
                  key={s.id}
                  onClick={() => toggleShot(s.id)}
                  className={`flex items-center gap-2 text-xs px-2.5 py-2 rounded-lg transition text-left ${
                    on ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:bg-[var(--bg-inset)]'
                  }`}
                >
                  <span className={`w-3.5 h-3.5 rounded flex items-center justify-center shrink-0 ${on ? 'bg-white' : 'border border-[var(--border)]'}`}>
                    {on && <Check size={10} className="text-black" strokeWidth={3} />}
                  </span>
                  {s.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* model/subject */}
        {category?.supports_model && (
          <div>
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Model / subject</label>
            {characters.length > 0 && (
              <select
                value={characterSlug}
                onChange={(e) => applyCharacter(e.target.value)}
                className="mt-1.5 w-full text-xs px-2.5 py-2 rounded-lg bg-[var(--bg-inset)] outline-none"
              >
                <option value="">— saved characters —</option>
                {characters.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
              </select>
            )}
            <div className="flex justify-end -mb-1">
              <Dictate
                title="Dictate the model description"
                onText={(t) => setModelDescription((v) => (v ? v.trimEnd() + ' ' + t : t))}
              />
            </div>
            <textarea
              value={modelDescription}
              onChange={(e) => setModelDescription(e.target.value)}
              rows={2}
              placeholder="e.g. a South Asian woman in her late 20s, shoulder-length dark hair"
              className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none resize-none placeholder:text-[var(--text-faint)]"
            />
          </div>
        )}

        <div>
          <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Background</label>
            <Dictate title="Dictate the background" onText={(t) => setBackground((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
          <input
            value={background}
            onChange={(e) => setBackground(e.target.value)}
            placeholder="e.g. warm blush studio wall"
            className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none placeholder:text-[var(--text-faint)]"
          />
        </div>

        <div>
          <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Extra direction</label>
            <Dictate title="Dictate the direction" onText={(t) => setExtra((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
          <textarea
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            rows={2}
            placeholder="Anything else about styling or mood"
            className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none resize-none placeholder:text-[var(--text-faint)]"
          />
        </div>

        <button
          onClick={run}
          disabled={!canRun}
          className="h-10 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition shrink-0"
        >
          {running ? <ActivityOrb state="working" size={20} label="Working…" /> : <Sparkles size={14} />}
          {running ? 'Generating…' : `Generate ${selectedShots.length || ''} shot${selectedShots.length === 1 ? '' : 's'}`}
        </button>
        {/* A set of shots is a queue: Stop clears the ones not started as well
            as the one being rendered. */}
        {running && (
          <button
            onClick={() => { void stopImage(); }}
            className="h-9 rounded-xl border border-[var(--border-soft)] text-xs text-[var(--text-dim)] hover:text-white hover:border-[var(--text-faint)] transition shrink-0"
          >
            Stop
          </button>
        )}
      </div>

      {/* ----------------------------------------------------------- results */}
      <div className={`flex-1 min-w-0 overflow-y-auto p-6 split-pane${split.on(1)}`}>
        {results.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center gap-2">
            <p className="text-sm text-[var(--text-faint)]">
              Add a product photo, pick the shots you want, and generate.
            </p>
            <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
              Uncloud re-photographs your actual product — the reference keeps its colour,
              print and stitching instead of inventing a new one.
            </p>
          </div>
        ) : (
          <>
            {doneCount > 0 && (
              <div className="flex justify-end mb-3">
                <button
                  onClick={exportAll}
                  className="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-full bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition"
                >
                  <FolderDown size={12} /> {inDesktop() ? `Export ${doneCount} to folder` : `Download ${doneCount}`}
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
            {results.map(({ job, url }) => (
              <div key={job.id} className="card overflow-hidden">
                <div className="aspect-[3/4] bg-[var(--bg-inset)] flex items-center justify-center">
                  {url ? (
                    <img src={url} alt={job.label ?? job.prompt} className="w-full h-full object-cover" />
                  ) : job.status === 'error' ? (
                    <div className="text-[11px] text-rose-400 px-4 text-center">{job.error}</div>
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-[var(--text-faint)]">
                      <ActivityOrb state="working" size={20} label="Working…" />
                      <span className="text-[11px]">
                        {job.total_steps ? `${job.step}/${job.total_steps}` : 'Queued'}
                      </span>
                    </div>
                  )}
                </div>
                <div className="px-3 py-2 text-[11px] text-[var(--text-dim)]">{job.label ?? 'Shot'}</div>
              </div>
            ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
