import { useEffect, useState } from 'react';
import { ArrowLeft, Drama, Pencil, Play, Plus } from 'lucide-react';
import CapabilityGate from '../components/CapabilityGate';
import ChatView from './ChatView';
import { engineStatus, getLibrary, listPersonas, savePersona, startEngine } from '../lib/sidecar';
import type { LocalModel, Persona } from '../lib/sidecar';
import { useLibraryVersion } from '../lib/library-changed';
import { PERSONA_PRESETS, PERSONA_REFERENCES } from '../lib/persona-presets';

const empty = { name: '', instructions: '', model_path: '' };
const field = 'w-full rounded-xl bg-[var(--bg-inset)] border border-[var(--border)] px-3 py-2 text-sm outline-none';

export default function PersonasView() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [models, setModels] = useState<LocalModel[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState(empty);
  const [composing, setComposing] = useState(false);
  const [active, setActive] = useState<Persona | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const version = useLibraryVersion();

  useEffect(() => {
    let alive = true;
    Promise.all([listPersonas(), getLibrary()]).then(([saved, library]) => {
      if (!alive) return;
      setPersonas(saved);
      setModels(library.filter(m => m.category === 'text' && m.ready));
    }).catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, [version]);

  async function save() {
    setBusy(true); setError('');
    try {
      const saved = await savePersona({ ...draft, model_path: draft.model_path || null }, editing ?? undefined);
      setPersonas(current => [saved, ...current.filter(p => p.id !== saved.id)]);
      setComposing(false); setEditing(null); setDraft(empty);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  async function begin(persona: Persona) {
    const model = models.find(m => m.path === persona.model_path);
    if (!model) { setError('Edit this persona and choose an installed model first.'); return; }
    setBusy(true); setError('');
    try {
      const status = await engineStatus();
      if (!status.running || status.model_path !== model.path) await startEngine(model.path, model.engine);
      setActive(persona);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  if (active) return <div className="h-full flex flex-col">
    <div className="px-5 py-2 border-b border-[var(--border-soft)] flex items-center gap-3">
      <button className="pill" onClick={() => setActive(null)}><ArrowLeft size={14} /> Personas</button>
      <details className="text-xs text-[var(--text-dim)] min-w-0">
        <summary className="cursor-pointer">Active persona: {active.name}</summary>
        <p className="whitespace-pre-wrap max-h-36 overflow-y-auto py-2">{active.instructions}</p>
      </details>
    </div>
    <div className="flex-1 min-h-0"><CapabilityGate names="chat"><ChatView key={active.id} persona={active} /></CapabilityGate></div>
  </div>;

  return <div className="h-full overflow-y-auto chassis-scroll">
    <div className="page-column flex flex-col gap-5">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2"><Drama size={22} /> Personas</h1>
          <p className="text-sm text-[var(--text-dim)] mt-2">Choose a profile, select a model, and bring it online.</p>
          <p className="text-xs text-[var(--text-faint)] mt-1">Persona instructions apply only in this workspace. Review and edit them before saving; ordinary Chat keeps the model’s own behaviour.</p>
        </div>
        <button className="pill" disabled={busy} onClick={() => { setDraft(empty); setEditing(null); setComposing(true); setError(''); }}><Plus size={14} /> New persona</button>
      </header>
      {error && <p role="alert" className="text-sm text-rose-400">{error}</p>}
      {!composing && <section aria-label="Included persona profiles" className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">Included profiles</h2>
        <p className="text-xs text-[var(--text-faint)]">Fictional styles inspired by the characters. No extra model or voice download is included.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {PERSONA_PRESETS.map(preset => <div key={preset.id} className="card p-4 flex flex-col items-start gap-2">
            <h3 className="text-sm font-medium">{preset.name}</h3>
            <p className="text-xs text-[var(--text-dim)] flex-1">{preset.summary}</p>
            <button className="pill" disabled={busy} aria-label={`Use ${preset.name} profile`} onClick={() => {
              setDraft({ name: preset.name, instructions: preset.instructions, model_path: '' });
              setEditing(null); setComposing(true); setError('');
            }}>Use profile</button>
          </div>)}
        </div>
        <details className="text-xs text-[var(--text-faint)]">
          <summary className="cursor-pointer">Character inspiration</summary>
          <div className="flex flex-col gap-1 pt-2">{PERSONA_REFERENCES.map(source =>
            <a key={source.url} href={source.url} target="_blank" rel="noreferrer" className="underline">{source.label}</a>)}</div>
        </details>
      </section>}
      {composing && <section className="card p-5 flex flex-col gap-4">
        <label className="text-xs flex flex-col gap-2">Name
          <input className={field} value={draft.name} maxLength={120} onChange={e => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label className="text-xs flex flex-col gap-2">Persona instructions
          <textarea className={`${field} min-h-40 resize-y`} value={draft.instructions} maxLength={32000}
            placeholder="Describe the role, personality, tone and setting you want."
            onChange={e => setDraft({ ...draft, instructions: e.target.value })} />
        </label>
        <label className="text-xs flex flex-col gap-2">Model
          <select className={field} value={draft.model_path} onChange={e => setDraft({ ...draft, model_path: e.target.value })}>
            <option value="">Choose a model before starting</option>
            {models.map(m => <option key={m.path} value={m.path}>{m.name}</option>)}
          </select>
        </label>
        <p className="text-xs text-[var(--text-faint)]">Saving does not load a model. Edits apply to new conversations; saved conversations retain the instructions they used.</p>
        <div className="flex gap-2">
          <button className="pill pill-on" disabled={busy || !draft.name.trim() || !draft.instructions.trim()} onClick={() => void save()}>Save persona</button>
          <button className="pill" disabled={busy} onClick={() => setComposing(false)}>Cancel</button>
        </div>
      </section>}
      {!personas.length && !composing && <p className="text-sm text-[var(--text-faint)]">Create your first persona to begin.</p>}
      {personas.map(persona => <section key={persona.id} className="card p-5 flex flex-col gap-3">
        <h2 className="text-base font-medium">{persona.name}</h2>
        <p className="text-sm text-[var(--text-dim)] whitespace-pre-wrap line-clamp-3">{persona.instructions}</p>
        <p className="text-xs text-[var(--text-faint)]">{models.find(m => m.path === persona.model_path)?.name ?? 'Choose an installed model in Edit'}</p>
        <div className="flex gap-2 flex-wrap">
          <button className="pill pill-on" disabled={busy} onClick={() => void begin(persona)}><Play size={13} /> {busy ? 'Preparing…' : 'Start conversation'}</button>
          <button className="pill" disabled={busy} onClick={() => { setEditing(persona.id); setDraft({ name: persona.name, instructions: persona.instructions, model_path: persona.model_path ?? '' }); setComposing(true); }}><Pencil size={13} /> Edit</button>

        </div>
      </section>)}
    </div>
  </div>;
}
