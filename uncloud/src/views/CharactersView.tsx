import { useEffect, useRef, useState } from 'react';
import { ImagePlus, Loader2, Plus, Trash2, UserRound, X } from 'lucide-react';
import { listCharacters, saveCharacter, deleteCharacter, uploadImage, characterReferenceUrl } from '../lib/sidecar';
import { characterListChanged } from '../lib/characters-changed';
import Dictate from '../components/Dictate';
import type { Character } from '../lib/sidecar';

export default function CharactersView() {
  const [chars, setChars] = useState<Character[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [refPath, setRefPath] = useState<string | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function refresh() {
    const list = await listCharacters();
    setChars(list);
    for (const c of list) {
      if (c.has_reference && !thumbs[c.slug]) {
        characterReferenceUrl(c.slug)
          .then((u) => setThumbs((t) => ({ ...t, [c.slug]: u })))
          .catch(() => undefined);
      }
    }
  }

  useEffect(() => { refresh(); }, []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    try {
      setRefPath(await uploadImage(file));
      setRefPreview(URL.createObjectURL(file));
    } catch (e) {
      alert(`Upload failed: ${e}`);
    } finally {
      setUploading(false);
    }
  }

  function reset() {
    setEditing(false);
    setName('');
    setDescription('');
    setRefPath(null);
    setRefPreview(null);
  }

  async function save() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await saveCharacter({ name: name.trim(), description: description.trim(), reference_path: refPath });
      reset();
      await refresh();
      characterListChanged();
    } catch (e) {
      alert(`Save failed: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  async function remove(slug: string) {
    if (!confirm('Delete this character?')) return;
    await deleteCharacter(slug);
    setThumbs((t) => { const n = { ...t }; delete n[slug]; return n; });
    refresh();
    characterListChanged();
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="flex items-start justify-between mb-1">
        <h1 className="text-2xl font-semibold">Characters</h1>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg btn-accent transition"
          >
            <Plus size={13} /> New character
          </button>
        )}
      </div>
      <p className="text-xs text-[var(--text-faint)] mb-6 max-w-xl">
        Saved subjects you can reuse across generations, so the same person shows up
        shot after shot. Available to every image model you have installed.
      </p>

      {editing && (
        <div className="card p-4 mb-6 max-w-xl flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">New character</h2>
            <button onClick={reset} className="text-[var(--text-faint)] hover:text-white transition">
              <X size={14} />
            </button>
          </div>

          <div>
            <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Name</label>
            <Dictate title="Dictate the name" onText={(t) => setName((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Studio Model A"
              className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-sm outline-none placeholder:text-[var(--text-faint)]"
            />
          </div>

          <div>
            <div className="flex items-center justify-between">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Traits</label>
            <Dictate title="Dictate the traits" onText={(t) => setDescription((v) => (v ? v.trimEnd() + ' ' + t : t))} />
          </div>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Age range, build, hair, skin tone, distinguishing features…"
              className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none resize-none placeholder:text-[var(--text-faint)]"
            />
            <p className="mt-1 text-[10px] text-[var(--text-faint)]">
              Traits get written into the prompt — this is what carries identity in Product shots,
              where the reference slot is taken by your product.
            </p>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Reference image</label>
            <input
              ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp"
              className="hidden" onChange={(e) => onFile(e.target.files?.[0])}
            />
            {refPreview ? (
              <div className="mt-1.5 relative group w-40">
                <img src={refPreview} alt="reference" className="w-full rounded-lg border border-[var(--border)]" />
                <button
                  onClick={() => { setRefPath(null); setRefPreview(null); }}
                  className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-black/70 flex items-center justify-center opacity-0 group-hover:opacity-100 touch:opacity-100 before:absolute before:-inset-2.5 before:content-[''] transition"
                >
                  <X size={12} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => fileInput.current?.click()}
                disabled={uploading}
                className="mt-1.5 w-40 h-24 rounded-lg border border-dashed border-[var(--border)] flex flex-col items-center justify-center gap-1.5 text-[var(--text-faint)] hover:border-[#3a3a42] transition"
              >
                {uploading ? <Loader2 size={15} className="animate-spin" /> : <ImagePlus size={16} />}
                <span className="text-[11px]">{uploading ? 'Uploading…' : 'Optional'}</span>
              </button>
            )}
          </div>

          <button
            onClick={save}
            disabled={!name.trim() || saving}
            className="h-9 rounded-lg btn-accent text-xs font-medium disabled:opacity-30 transition"
          >
            {saving ? 'Saving…' : 'Save character'}
          </button>
        </div>
      )}

      {chars.length === 0 && !editing ? (
        <div className="text-sm text-[var(--text-faint)]">No characters saved yet.</div>
      ) : (
        <div className="grid grid-cols-4 gap-3 max-w-4xl">
          {chars.map((c) => (
            <div key={c.slug} className="card overflow-hidden group">
              <div className="aspect-square bg-[var(--bg-inset)] flex items-center justify-center">
                {thumbs[c.slug] ? (
                  <img src={thumbs[c.slug]} alt={c.name} className="w-full h-full object-cover" />
                ) : (
                  <UserRound size={22} className="text-[var(--text-faint)]" />
                )}
              </div>
              <div className="px-3 py-2 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-xs truncate">{c.name}</div>
                  {c.description && (
                    <div className="text-[10px] text-[var(--text-faint)] line-clamp-2 mt-0.5">{c.description}</div>
                  )}
                </div>
                <button
                  onClick={() => remove(c.slug)}
                  className="text-[var(--text-faint)] hover:text-rose-400 transition opacity-0 group-hover:opacity-100 touch:opacity-100 relative before:absolute before:-inset-2.5 before:content-[''] shrink-0"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
