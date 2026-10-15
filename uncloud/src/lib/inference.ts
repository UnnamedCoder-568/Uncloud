import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiPost } from './sidecar';
import { onLibraryChange } from './library-changed';

export type InferenceValues = Record<string, number | string | boolean | string[] | Record<string, unknown>>;
export interface InferenceInfo {
  saved: { version: number; presets: Record<string, InferenceValues>; defaults: Record<string, InferenceValues> };
  active: null | { model_path: string; engine: string; context_limit: number; profile: {
    parameters: Record<string, number>; sources: Record<string, string>; max_output_tokens?: number;
    recommendation?: { id?: string; source?: string; verified?: string; native_mode?: string };
    mode_parameters?: Record<string, Record<string, number>>;
    explicit_parameters?: Record<string, number>;
    capabilities: { fields: string[]; backend_version: string; template: string;
      runtime_defaults?: { max_tokens?: number };
      reasoning: { levels: string[]; explanation: string; mechanism: string; default?: string;
        budget?: { mechanism: string; closing_tokens: number } } };
  } };
}
export const getInference = () => api<InferenceInfo>('/api/inference');
export const saveInference = (values: InferenceValues, preset = '', scope = 'model', scope_id = '') =>
  apiPost<InferenceInfo['saved']>('/api/inference', { values, preset, scope, scope_id });

export function resolvedDefaults(report: InferenceInfo, modelPath?: string | null, conversationId?: string | null,
  manual: InferenceValues = {}): InferenceValues {
  let legacy: InferenceValues = {};
  if (!Object.hasOwn(report.saved.defaults, `model:${modelPath}`)) {
    try {
      for (const [storage, field] of [['temperatures', 'temperature'], ['replyBudgets', 'max_tokens']]) {
        const value = JSON.parse(localStorage.getItem(`uncloud.chat.${storage}`) || '{}')[modelPath ?? ''];
        if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) legacy[field] = Number(value);
      }
    } catch { legacy = {}; }
  }
  return { ...legacy, ...(report.saved.defaults[`model:${modelPath}`] ?? {}),
    ...(report.saved.defaults[`conversation:${conversationId}`] ?? {}), ...manual };
}

export function useInference(modelPath?: string | null, conversationId?: string | null, rememberManual = false) {
  const [info, setInfo] = useState<InferenceInfo | null>(null);
  const [initialManual] = useState<InferenceValues | null>(() => {
    try {
      if (!rememberManual) return {};
      const stored = localStorage.getItem('uncloud.chat.manualInference');
      if (stored === null) return null; // Migrate the current model's saved overrides once.
      const saved = JSON.parse(stored);
      return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
    } catch { return null; }
  });
  const [values, setValues] = useState<InferenceValues>(initialManual ?? {});
  const manual = useRef<InferenceValues | null>(initialManual);
  const changeValues = useCallback((next: InferenceValues) => {
    manual.current = next;
    setValues(next);
    if (rememberManual) {
      try { localStorage.setItem('uncloud.chat.manualInference', JSON.stringify(next)); }
      catch { /* Controls remain usable without storage. */ }
    }
  }, [rememberManual]);
  const refresh = useCallback(async () => {
    const report = await getInference();
    setInfo(report);

  }, []);
  useEffect(() => {
    let alive = true;
    getInference().then(report => {
      if (!alive) return;
      setInfo(report);
      if (rememberManual) {
        if (!modelPath) return;
        if (manual.current === null) {
          manual.current = resolvedDefaults(report, modelPath, conversationId);
          try { localStorage.setItem('uncloud.chat.manualInference', JSON.stringify(manual.current)); }
          catch { /* Session overrides still work. */ }
        }
        setValues(manual.current);
      } else {
        setValues(resolvedDefaults(report, modelPath, conversationId, manual.current ?? {}));
      }
    }).catch(() => {});
    return () => { alive = false; };
  }, [modelPath, conversationId, rememberManual]);
  useEffect(() => onLibraryChange(() => { void refresh().catch(() => {}); }), [refresh]);
  return { info, values, setValues: changeValues, refresh };
}
