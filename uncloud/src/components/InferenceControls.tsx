import { useEffect, useState } from 'react';
import { api, apiPost } from '../lib/sidecar';
import { presetValues, saveInference } from '../lib/inference';
import type { InferenceInfo, InferenceValues } from '../lib/inference';

const CORE = ['temperature', 'top_p', 'top_k', 'min_p', 'repetition_penalty',
  'presence_penalty', 'frequency_penalty', 'max_tokens', 'seed'];
const LABELS: Record<string, string> = { temperature: 'Temperature', top_p: 'Top P', top_k: 'Top K',
  min_p: 'Min P', repetition_penalty: 'Repeat penalty', presence_penalty: 'Presence penalty',
  frequency_penalty: 'Frequency penalty', max_tokens: 'Reply budget · includes reasoning', seed: 'Seed' };

export default function InferenceControls({ info, values, onChange, onRefresh, conversationId, compact = false }:
  { info: InferenceInfo | null; values: InferenceValues; onChange: (v: InferenceValues) => void;
    onRefresh: () => Promise<void>; conversationId?: string | null; compact?: boolean }) {
  const [name, setName] = useState('');
  const [projectId, setProjectId] = useState('');
  const [status, setStatus] = useState('');
  const [selected, setSelected] = useState('Auto');
  const [jsonText, setJsonText] = useState('');
  const [effective, setEffective] = useState<Record<string, unknown> | null>(null);
  const active = info?.active;
  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      void apiPost<Record<string, unknown>>('/api/inference/preview', { values })
        .then(v => { if (alive) setEffective(v); }).catch(e => { if (alive) setEffective({ error: String(e) }); });
    }, 200);
    return () => { alive = false; clearTimeout(timer); };
  }, [values, active?.model_path]);
  if (!active) return <p className="text-xs faint">Load a model to see its supported controls.</p>;
  const cap = active.profile.capabilities;
  if (!cap) return <p className="text-xs faint">Reload this model to discover its supported controls.</p>;
  const update = (key: string, value: InferenceValues[string] | undefined) => {
    const next = { ...values };
    if (value === undefined) delete next[key]; else next[key] = value;
    setSelected('Custom'); onChange(next);
  };
  const save = async (preset = '', scope = 'model') => {
    try {
      await saveInference(values, preset, scope, scope === 'conversation' ? conversationId ?? '' : scope === 'project' ? projectId : active.model_path);
      setStatus(preset ? 'Preset saved.' : 'Defaults saved.');
      await onRefresh();
    } catch (e) { setStatus(e instanceof Error ? e.message : String(e)); }
  };
  const choose = (preset: string) => {
    setSelected(preset); onChange(info!.saved.presets[preset] ?? presetValues(preset, info!));
  };
  return <section className={`flex flex-col gap-3 ${compact ? 'text-xs' : 'card p-5'}`}>
    <div className="flex items-center justify-between gap-3"><h2 className="text-sm">Model controls</h2>
      <select className="input !w-auto" aria-label="Inference preset" value={selected} onChange={e => choose(e.target.value)}>
        {['Auto', 'Fast', 'Balanced', 'Deep', 'Creative', 'Deterministic', 'Custom', ...Object.keys(info!.saved.presets)].map(label =>
          <option key={label} value={label} disabled={(label === 'Deep' && !cap.reasoning.levels.includes('high')) ||
            (label === 'Fast' && !cap.reasoning.levels.includes('off')) ||
            (label === 'Creative' && active.profile.parameters.temperature === undefined)}>{label}</option>)}
      </select>
    </div>
    <label className="flex flex-col gap-1">Thinking effort
      <select className="input" value={String(values.reasoning ?? 'auto')} onChange={e => update('reasoning', e.target.value)}>
        {['auto', 'off', 'low', 'medium', 'high', 'max'].map(level => <option key={level} disabled={!cap.reasoning.levels.includes(level)} value={level}>
          {level[0].toUpperCase() + level.slice(1)}{!cap.reasoning.levels.includes(level) ? ' · unsupported' : ''}</option>)}
      </select><span className="faint text-[11px]">{cap.reasoning.explanation}</span>
    </label>
    <details><summary className="cursor-pointer text-[var(--text-dim)]">Sampling and reply budget</summary>
      <div className="grid grid-cols-2 gap-3 mt-3">{CORE.filter(key => cap.fields.includes(key)).map(key => <label key={key} className="flex flex-col gap-1 text-xs">
        {LABELS[key]}<input className="input" type="number" step={['seed', 'top_k', 'max_tokens'].includes(key) ? '1' : 'any'}
          value={values[key] === undefined ? '' : String(values[key])}
          placeholder={active.profile.parameters[key] === undefined ? 'Auto · backend' : `Auto · ${active.profile.parameters[key]}`}
          onChange={e => update(key, e.target.value === '' ? undefined : Number(e.target.value))} />
      </label>)}</div>
      {cap.fields.includes('stop') && <label className="flex flex-col gap-1 mt-3 text-xs">Stop sequences · one per line
        <textarea className="input" rows={2} value={Array.isArray(values.stop) ? values.stop.join('\n') : String(values.stop ?? '')}
          onChange={e => update('stop', e.target.value ? e.target.value.split('\n').filter(Boolean) : undefined)} />
      </label>}
    </details>
    <details><summary className="cursor-pointer text-[var(--text-dim)]">System prompt</summary>
      <p className="text-[11px] faint mt-2">Custom replaces the Chat prompt. An empty custom prompt sends no system message. Chisel retains its required tool contract.</p>
      <label className="flex gap-2 mt-2"><input type="checkbox" checked={values.system_prompt !== undefined}
        onChange={e => update('system_prompt', e.target.checked ? '' : undefined)} /> Use custom prompt</label>
      {values.system_prompt !== undefined && <textarea className="input mt-2" rows={4} value={String(values.system_prompt)}
        onChange={e => update('system_prompt', e.target.value)} />}
    </details>
    <details><summary className="cursor-pointer text-[var(--text-dim)]">Advanced and effective configuration</summary>
      <p className="text-[11px] faint mt-2">{active.engine} · {cap.backend_version} · {active.context_limit.toLocaleString()} context tokens. Unsupported settings are rejected.</p>
      <pre className="text-[11px] whitespace-pre-wrap break-all mt-2">{JSON.stringify({ recommendations: active.profile.parameters,
        sources: active.profile.sources, overrides: values, effective_request: effective,
        unsupported_native_defaults: Object.keys(active.profile.parameters).filter(k => !cap.fields.includes(k)),
        supported: cap.fields }, null, 2)}</pre>
      <textarea className="input mt-2 font-mono text-xs" aria-label="Advanced inference JSON" rows={4}
        placeholder="Paste supported overrides as JSON" value={jsonText} onChange={e => setJsonText(e.target.value)} />
      <button className="pill mt-2" onClick={() => { try { const parsed = JSON.parse(jsonText); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Use a JSON object.'); onChange(parsed); setSelected('Custom'); setStatus('Overrides applied. They will be validated before inference.'); } catch (e) { setStatus(String(e)); } }}>Apply JSON</button>
      <details className="mt-3"><summary className="cursor-pointer">Inspect native template</summary><pre className="text-[11px] whitespace-pre-wrap break-all">{cap.template || 'Template is owned by the backend.'}</pre></details>
    </details>
    <details><summary className="cursor-pointer text-[var(--text-dim)]">Save and manage presets</summary>
      <div className="flex flex-wrap gap-2 mt-3"><button className="pill" onClick={() => void save()}>Save model defaults</button>
        {conversationId && <button className="pill" onClick={() => void save('', 'conversation')}>Save for this conversation</button>}
        <button className="pill" onClick={() => { onChange({}); setSelected('Auto'); }}>Use native defaults</button></div>
      <div className="flex gap-2 mt-3"><input className="input" placeholder="Preset name" value={name} onChange={e => setName(e.target.value)} />
        <button className="pill" disabled={!name.trim()} onClick={() => void save(name.trim())}>Save</button></div>
      <div className="flex gap-2 mt-3"><input className="input" aria-label="Project scope ID" placeholder="Project ID · advanced scope" value={projectId} onChange={e => setProjectId(e.target.value)} />
        <button className="pill" disabled={!projectId.trim()} onClick={() => void save('', 'project')}>Save project defaults</button></div>
      <button className="pill mt-2" disabled={!info!.saved.defaults[`project:${projectId.trim()}`]} onClick={() => {
        onChange({ ...(info!.saved.defaults[`model:${active.model_path}`] ?? {}),
          ...info!.saved.defaults[`project:${projectId.trim()}`],
          ...(info!.saved.defaults[`conversation:${conversationId}`] ?? {}) });
        setSelected('Custom'); setStatus('Project settings applied. This does not read project files.');
      }}>Apply project defaults</button>
      {Object.keys(info!.saved.presets).map(preset => <div key={preset} className="flex items-center justify-between mt-2"><button onClick={() => choose(preset)}>{preset}</button>
        <button className="pill" onClick={async () => { try { await api(`/api/inference/presets/${encodeURIComponent(preset)}`, { method: 'DELETE' }); await onRefresh(); } catch (e) { setStatus(String(e)); } }}>Delete</button></div>)}
      <div className="flex gap-2 mt-3"><button className="pill" onClick={() => { const blob = new Blob([JSON.stringify({ version: 1, presets: info!.saved.presets }, null, 2)], { type: 'application/json' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'uncloud-presets.json'; a.click(); URL.revokeObjectURL(a.href); }}>Export</button>
        <label className="pill cursor-pointer">Import<input type="file" className="hidden" accept=".json" onChange={async e => { try { const file = e.target.files?.[0]; if (!file || file.size > 500000) throw new Error('Choose a preset JSON file under 500 KB.'); const data = JSON.parse(await file.text()); await apiPost('/api/inference/import', data); await onRefresh(); setStatus('Presets imported.'); } catch (e) { setStatus(String(e)); } }} /></label></div>
    </details>
    {status && <p className="text-xs text-[var(--text-dim)]" role="status">{status}</p>}
  </section>;
}
