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
      reasoning: { levels: string[]; explanation: string; mechanism: string;
        budget?: { mechanism: string; closing_tokens: number } } };
  } };
}
export const getInference = () => api<InferenceInfo>('/api/inference');
export const saveInference = (values: InferenceValues, preset = '', scope = 'model', scope_id = '') =>
  apiPost<InferenceInfo['saved']>('/api/inference', { values, preset, scope, scope_id });

export function resolvedDefaults(report: InferenceInfo, modelPath?: string | null, conversationId?: string | null): InferenceValues {
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
    ...(report.saved.defaults[`conversation:${conversationId}`] ?? {}) };
}

export function useInference(modelPath?: string | null, conversationId?: string | null) {
  const [info, setInfo] = useState<InferenceInfo | null>(null);
  const [values, setValues] = useState<InferenceValues>({});
  const previous = useRef({ modelPath, conversationId });
  const refresh = useCallback(async () => {
    const report = await getInference();
    setInfo(report);

  }, []);
  useEffect(() => {
    let alive = true;
    const freshConversation = previous.current.modelPath === modelPath &&
      !previous.current.conversationId && !!conversationId;
    previous.current = { modelPath, conversationId };
    getInference().then(report => {
      if (!alive) return;
      setInfo(report);
      if (!freshConversation || report.saved.defaults[`conversation:${conversationId}`])
        setValues(resolvedDefaults(report, modelPath, conversationId));
    }).catch(() => {});
    return () => { alive = false; };
  }, [modelPath, conversationId]);
  useEffect(() => onLibraryChange(() => { void refresh().catch(() => {}); }), [refresh]);
  return { info, values, setValues, refresh };
}

/** Presets use discovered recommendations; settings are always shown before sending. */
export function presetValues(name: string, info: InferenceInfo): InferenceValues {
  const profile = info.active?.profile;
  if (!profile) return {};
  const fields = profile.capabilities.fields;
  const thinking = profile.capabilities.reasoning.levels;
  if (name === 'Fast') return thinking.includes('off') ? { reasoning: 'off' } : {};
  if (name === 'Deep') return thinking.includes('high') ? { reasoning: 'high' } : {};
  if (name === 'Deterministic') return { ...(fields.includes('temperature') ? { temperature: 0 } : {}),
    ...(fields.includes('seed') ? { seed: 0 } : {}) };
  if (name === 'Creative' && profile.parameters.temperature !== undefined)
    return { temperature: profile.parameters.temperature * 1.2 };
  return {};
}
