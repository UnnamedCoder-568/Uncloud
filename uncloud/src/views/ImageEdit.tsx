import { useDismiss } from '../lib/useDismiss';
import ActivityOrb from '../components/ActivityOrb';
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ImagePlus, Wand2, X, ArrowRight } from 'lucide-react';
import { getLibrary, uploadImage, editImage, getImageJob, fetchImageBlobUrl, stopImage } from '../lib/sidecar';
import { onWake } from '../lib/awake';
import Dictate from '../components/Dictate';
import SaveActions from '../components/SaveActions';
import AddFromDisk from '../components/AddFromDisk';
import { useLibraryVersion } from '../lib/library-changed';
import type { LocalModel, ImageJob } from '../lib/sidecar';
import { SplitTabs, useSplit } from '../components/Split';

const PRESETS = [
  { label: 'Replace background', hint: 'Replace the background with a plain warm beige studio wall. Keep the subject exactly as-is.' },
  { label: 'Add text', hint: 'Add the text "NEW ARRIVAL" in clean modern sans-serif across the upper third of the image.' },
  { label: 'Text behind subject', hint: 'Add large bold text "SALE" behind the subject so the subject overlaps and partially covers the letters.' },
  { label: 'Add logo', hint: 'Add a small minimal logo mark in the bottom-right corner.' },
  { label: 'Change colour', hint: 'Change the colour of the garment to deep emerald green. Keep the print, embroidery and texture identical.' },
  { label: 'Clean up', hint: 'Remove any clutter and distracting objects from the background. Keep the subject untouched.' },
];

export default function ImageEdit() {
  const libraryVersion = useLibraryVersion();
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useDismiss(pickerOpen, () => setPickerOpen(false));

  const [refPath, setRefPath] = useState<string | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const [instruction, setInstruction] = useState('');
  const [job, setJob] = useState<ImageJob | null>(null);
  const [outUrl, setOutUrl] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getLibrary().then((list) => {
      const editors = list.filter((m) => m.category === 'image' && m.ready && m.capabilities.includes('edit'));
      setModels(editors);
      setModel((p) => p ?? editors[0] ?? null);
    });
  }, [libraryVersion]);

  // One watching loop for the life of the view, reading through refs — see
  // lib/awake for why a page can come back knowing nothing.
  const jobRef = useRef(job);
  const outRef = useRef(outUrl);
  useEffect(() => { jobRef.current = job; }, [job]);
  useEffect(() => { outRef.current = outUrl; }, [outUrl]);

  useEffect(() => {
    let stopped = false;

    const sync = async () => {
      const current = jobRef.current;
      if (stopped || !current) return;
      if (!current.done) {
        const updated = await getImageJob(current.id).catch(() => null);
        if (stopped) return;
        if (updated) setJob(updated);
      }
      const latest = jobRef.current;
      if (!stopped && latest?.done && latest.status === 'done' && !outRef.current) {
        const url = await fetchImageBlobUrl(latest.id).catch(() => null);
        if (url && !stopped) setOutUrl(url);
      }
    };

    const t = setInterval(() => { void sync(); }, 1200);
    const wake = onWake(() => { void sync(); });
    return () => { stopped = true; clearInterval(t); wake(); };
  }, []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    try {
      setRefPath(await uploadImage(file));
      setRefPreview(URL.createObjectURL(file));
      setOutUrl(null);
      setJob(null);
    } catch (e) {
      alert(`Upload failed: ${e}`);
    } finally {
      setUploading(false);
    }
  }

  async function run() {
    if (!model || !refPath || !instruction.trim() || (job && !job.done)) return;
    setOutUrl(null);
    setJob(await editImage(model.path, instruction.trim(), refPath, model.catalog_id));
  }

  /** Send the current result back round as the new input, so edits can stack. */
  async function useResultAsInput() {
    if (!outUrl || !job) return;
    const blob = await (await fetch(outUrl)).blob();
    await onFile(new File([blob], 'edited.png', { type: 'image/png' }));
  }

  const busy = !!job && !job.done;

  const split = useSplit(busy);

  return (
    <div className="h-full flex split">
      <SplitTabs split={split} labels={['Edit', 'Result']} />
      <div className={`w-[320px] shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5 split-pane${split.on(0)}`}>
        <div ref={pickerRef} className="relative">
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

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Image</label>
          <input
            ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp"
            className="hidden" onChange={(e) => onFile(e.target.files?.[0])}
          />
          {refPreview ? (
            <div className="mt-1.5 relative group">
              <img src={refPreview} alt="source" className="w-full rounded-lg border border-[var(--border)]" />
              <button
                onClick={() => { setRefPath(null); setRefPreview(null); setOutUrl(null); setJob(null); }}
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
              <span className="text-[11px]">{uploading ? 'Uploading…' : 'Add an image'}</span>
            </button>
          )}
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Quick edits</label>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => setInstruction(p.hint)}
                className="text-[11px] px-2.5 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-faint)] hover:text-[var(--text-dim)] transition"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Describe the edit</label>
            <Dictate title="Dictate the edit" onText={(t) => setInstruction((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={5}
            placeholder="Describe the change, and what must stay the same…"
            className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none resize-none placeholder:text-[var(--text-faint)]"
          />
          <p className="mt-1.5 text-[10px] text-[var(--text-faint)] leading-relaxed">
            Edits are described, not brushed — say which region you mean
            ("the upper-left corner", "behind the model") and what must stay untouched.
          </p>
        </div>

        <button
          onClick={run}
          disabled={!model || !refPath || !instruction.trim() || busy}
          className="h-10 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition"
        >
          {busy ? <ActivityOrb state="working" size={20} label="Working…" /> : <Wand2 size={14} />}
          {busy ? 'Editing…' : 'Apply edit'}
        </button>
      </div>

      <div className={`flex-1 min-w-0 overflow-y-auto p-6 flex items-center justify-center split-pane${split.on(1)}`}>
        {outUrl ? (
          <div className="flex flex-col items-center gap-3 max-h-full">
            <img src={outUrl} alt="result" className="max-h-[70vh] rounded-xl border border-[var(--border)]" />
            <button
              onClick={useResultAsInput}
              className="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-full bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition"
            >
              Continue editing this <ArrowRight size={12} />
            </button>
            <SaveActions
              path={job?.output_path ?? null}
              onDiscarded={() => {
                URL.revokeObjectURL(outUrl);
                setOutUrl(null);
                setJob(null);
              }}
            />
          </div>
        ) : busy ? (
          <div className="flex flex-col items-center gap-3 text-[var(--text-dim)]">
            <ActivityOrb state="working" size={20} label="Working…" />
            <span className="text-sm">
              {job?.total_steps ? `Editing — step ${job.step}/${job.total_steps}` : 'Editing…'}
            </span>
            <button
              onClick={() => { void stopImage(); }}
              className="text-xs px-3 py-1 rounded-full border border-[var(--border-soft)] text-[var(--text-dim)] hover:text-white hover:border-[var(--text-faint)] transition"
            >
              Stop
            </button>
          </div>
        ) : job?.status === 'cancelled' ? (
          <div className="text-sm text-[var(--text-faint)]">Stopped.</div>
        ) : job?.status === 'error' ? (
          <div className="text-sm text-rose-400 max-w-md text-center">{job.error}</div>
        ) : (
          <div className="text-sm text-[var(--text-faint)]">Add an image and describe the change.</div>
        )}
      </div>
    </div>
  );
}
