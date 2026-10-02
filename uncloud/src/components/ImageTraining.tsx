import { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { getImageTrainingTemplate, prepareImageTraining, startImageTraining, getLibrary, type LocalModel } from '../lib/sidecar';
import ActivityOrb from './ActivityOrb';
import { inDesktop } from '../lib/platform';

export default function ImageTraining({ onChange }: { onChange: () => void }) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [config, setConfig] = useState('');
  const [name, setName] = useState('');
  const [plan, setPlan] = useState<{ examples: number; estimated_memory_gb: number; note: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    void getLibrary().then(all => setModels(all.filter(m => m.category === 'image' && m.engine === 'mflux' && m.ready))).catch(e => setError(e.message));
    void getImageTrainingTemplate().then(value => setConfig(JSON.stringify(value.config, null, 2))).catch(e => setError(e.message));
  }, []);
  function change(key: string, value: string) {
    try { setConfig(JSON.stringify({ ...JSON.parse(config), [key]: value }, null, 2)); setPlan(null); }
    catch { setError('Correct the configuration JSON first.'); }
  }
  async function check() {
    setBusy(true); setError(''); setPlan(null);
    try { setPlan(await prepareImageTraining(JSON.parse(config))); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function start() {
    setBusy(true); setError('');
    try { await startImageTraining(JSON.parse(config), name); onChange(); setPlan(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const fields = [
    { label: 'Epochs', path: ['training_loop', 'num_epochs'], min: 1, step: 1 },
    { label: 'Batch size', path: ['training_loop', 'batch_size'], min: 1, step: 1 },
    { label: 'Learning rate', path: ['optimizer', 'learning_rate'], min: 0.0000001, step: 0.000001 },
    { label: 'Maximum resolution', path: ['max_resolution'], min: 64, step: 64 },
  ];
  function numberValue(path: string[]): number | '' {
    try { const value = path.reduce((obj, key) => obj[key], JSON.parse(config)); return typeof value === 'number' ? value : ''; }
    catch { return ''; }
  }
  function setNumber(path: string[], value: string) {
    if (!value || !Number.isFinite(Number(value))) return;
    try {
      const next = JSON.parse(config);
      const parent = path.slice(0, -1).reduce((obj, key) => obj[key], next);
      parent[path[path.length - 1]] = Number(value);
      setConfig(JSON.stringify(next, null, 2)); setPlan(null);
    } catch { setError('Correct the advanced configuration first.'); }
  }
  return <section className="card p-4 flex flex-col gap-3">
    <h2 className="text-sm">Image LoRA training · offline</h2>
    <p className="text-xs text-[var(--text-dim)]">Train a diffusion adapter from images and matching caption .txt files. All weights and model-required training adapters must already be local. Apple Silicon with MFlux is required.</p>
    <label className="text-xs flex flex-col gap-1">Local image model
      <select className="input" onChange={async e => {
        const selected = models.find(m => m.path === e.target.value);
        if (!selected) return;
        setPlan(null); setError('');
        const family = selected.mflux_base?.replaceAll('_', '-');
        try {
          const value = await getImageTrainingTemplate(family ?? 'unknown');
          setConfig(JSON.stringify({...value.config, model_path: selected.path}, null, 2));
        } catch (e) {
          change('model_path', selected.path);
          try { setConfig(JSON.stringify({...JSON.parse(config), model_path: selected.path, model: family ?? ''}, null, 2)); } catch { /* keep validation error visible */ }
          setError(`${e instanceof Error ? e.message : String(e)} Review the model family and target layers before checking.`);
        }
      }} defaultValue="">
        <option value="">Choose a model…</option>{models.map(m => <option key={m.path} value={m.path}>{m.name}</option>)}
      </select>
    </label>
    <button className="pill self-start" disabled={!inDesktop()} onClick={async () => { try { const path = await open({directory: true}); if (typeof path === 'string') change('data', path); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } }}>Choose image and caption folder…</button>
    {!inDesktop() && <p className="text-xs text-[var(--text-faint)]">Choose the dataset on the computer running Uncloud.</p>}
    <label className="text-xs flex flex-col gap-1">Adapter name<input className="input" value={name} onChange={e => setName(e.target.value)} /></label>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {fields.map(field => <label key={field.label} className="field"><span className="label">{field.label}</span><input type="number" className="input" value={numberValue(field.path)} min={field.min} step={field.step} onChange={e => setNumber(field.path, e.target.value)} /></label>)}
    </div>
    <p className="text-xs text-[var(--text-faint)]">Starting values come from the installed engine’s template. Check compatibility before training.</p>
    <details className="training-disclosure"><summary>Advanced training configuration</summary><label className="text-xs flex flex-col gap-1 mt-3">Training configuration
      <textarea className="input font-mono text-xs min-h-64" value={config} onChange={e => {setConfig(e.target.value); setPlan(null);}} />
    </label>
    </details>
    <p className="text-xs text-[var(--text-faint)]">The installed engine’s example targets Z-Image. For another family, set its model ID and supported target layers. The configuration exposes epochs, batch size, rank, learning rate, precision, resolution and checkpoint interval.</p>
    {error && <p role="alert" className="text-xs">{error}</p>}
    {busy && <ActivityOrb label="Checking training configuration…" />}
    {plan && <p className="text-xs">{plan.examples} examples · estimated {plan.estimated_memory_gb} GB. {plan.note}</p>}
    <div className="flex gap-2"><button className="pill" disabled={busy || !config} onClick={() => void check()}>Check dataset and model</button>
      <button className="btn-accent" disabled={busy || !plan} onClick={() => void start()}>Train image LoRA</button></div>
  </section>;
}
