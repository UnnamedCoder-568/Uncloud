import { invoke } from '@tauri-apps/api/core';

export interface SidecarInfo {
  port: number;
  token: string;
}

let cached: SidecarInfo | null = null;

export async function getSidecarInfo(): Promise<SidecarInfo> {
  if (cached) return cached;
  for (let i = 0; i < 60; i++) {
    const info = await invoke<SidecarInfo | null>('get_sidecar_info');
    if (info) {
      cached = info;
      return info;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('Uncloud engine never became available');
}

async function baseUrl(): Promise<string> {
  const { port } = await getSidecarInfo();
  return `http://127.0.0.1:${port}`;
}

async function authHeaders(): Promise<Record<string, string>> {
  const { token } = await getSidecarInfo();
  return { Authorization: `Bearer ${token}` };
}

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const url = `${await baseUrl()}${path}`;
  const headers = { ...(await authHeaders()), ...(opts.body ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) };
  const resp = await fetch(url, { ...opts, headers });
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
}

export interface Settings {
  models_dir: string;
  onboarded: boolean;
  agent_device_access: boolean;
  keep_awake: boolean;
  hf_token_set: boolean;
}

export interface CatalogEntry {
  id: string;
  name: string;
  category: string;
  engine: string;
  repo: string;
  size_gb: number;
  description: string;
  tags: string[];
  context_length: number | null;
  offline_capable: boolean;
  installed: boolean;
}

export interface LocalModel {
  id: string;
  name: string;
  category: string;
  engine: string;
  path: string;
  size_gb: number;
  catalog_id: string | null;
  tags: string[];
  ready: boolean;
  note: string | null;
  capabilities: string[];
}

export interface DownloadState {
  id: string;
  catalog_id: string;
  name: string;
  status: 'pending' | 'downloading' | 'done' | 'error' | 'cancelled';
  downloaded_bytes: number;
  total_bytes: number;
  percent: number;
  speed_bytes_s: number;
  error: string | null;
  dest: string;
}

export interface EngineStatus {
  running: boolean;
  model_path?: string;
  engine?: string;
  port?: number;
}

export async function getSettings() {
  return api<Settings>('/api/settings');
}
export async function setModelsDir(path: string) {
  return apiPost('/api/settings/models_dir', { path });
}
export async function markOnboarded() {
  return apiPost('/api/settings/onboarded');
}
export async function setDeviceAccess(enabled: boolean) {
  return apiPost('/api/settings/agent_device_access', { enabled });
}
export async function setHfToken(token: string) {
  return apiPost('/api/settings/hf_token', { token });
}
export async function getCatalog() {
  return api<CatalogEntry[]>('/api/catalog');
}
export async function getLibrary() {
  return api<LocalModel[]>('/api/library');
}
export async function startDownload(catalog_id: string) {
  return apiPost<DownloadState>('/api/downloads', { catalog_id });
}
export async function listDownloads() {
  return api<DownloadState[]>('/api/downloads');
}
export async function cancelDownload(id: string) {
  return apiPost(`/api/downloads/${id}/cancel`);
}
export async function startEngine(model_path: string, engine: string) {
  return apiPost<{ running: boolean; port: number; engine: string }>('/api/engine/start', { model_path, engine });
}
export async function stopEngine() {
  return apiPost('/api/engine/stop');
}
export async function engineStatus() {
  return api<EngineStatus>('/api/engine/status');
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export async function* streamChat(messages: ChatMessage[]): AsyncGenerator<string> {
  const url = `${await baseUrl()}/api/chat`;
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' };
  const resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ messages }) });
  if (!resp.ok || !resp.body) throw new Error(`Chat failed: ${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') return;
      try {
        const json = JSON.parse(data);
        const delta = json.choices?.[0]?.delta?.content;
        if (delta) yield delta;
      } catch {
        // ignore partial/malformed chunk
      }
    }
  }
}

export interface ImageJob {
  id: string;
  prompt: string;
  status: 'pending' | 'running' | 'done' | 'error';
  step: number;
  total_steps: number;
  done: boolean;
  error: string | null;
  kind: 'generate' | 'edit';
  label: string | null;
}

export interface ImageGenerateOptions {
  negative_prompt?: string;
  steps?: number;
  guidance?: number;
  width?: number;
  height?: number;
  seed?: number;
}

export async function generateImage(model_path: string, engine: string, prompt: string, catalog_id: string | null, opts: ImageGenerateOptions = {}) {
  return apiPost<ImageJob>('/api/image/generate', { model_path, engine, prompt, catalog_id, ...opts });
}
export async function getImageJob(id: string) {
  return api<ImageJob>(`/api/image/jobs/${id}`);
}
export interface ShotType {
  id: string;
  name: string;
  aspect: 'portrait' | 'square' | 'landscape';
}

export interface ProductCategory {
  id: string;
  name: string;
  description: string;
  supports_model: boolean;
  shots: ShotType[];
}

export interface Character {
  slug: string;
  name: string;
  description: string;
  tags: string[];
  created_at: number;
  has_reference: boolean;
  reference_path: string | null;
}

export async function uploadImage(file: File): Promise<string> {
  const form = new FormData();
  form.append('file', file, file.name);
  const resp = await fetch(`${await baseUrl()}/api/image/upload`, {
    method: 'POST', headers: await authHeaders(), body: form,
  });
  if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);
  return (await resp.json()).path as string;
}

export async function editImage(
  model_path: string,
  prompt: string,
  reference_path: string,
  catalog_id: string | null,
  opts: { steps?: number; guidance?: number; width?: number; height?: number; seed?: number; strength?: number } = {},
) {
  return apiPost<ImageJob>('/api/image/edit', { model_path, prompt, reference_path, catalog_id, ...opts });
}

export async function getProductCategories() {
  return api<ProductCategory[]>('/api/product/categories');
}

export async function generateProductShots(body: {
  model_path: string;
  reference_path: string;
  category: string;
  shots: string[];
  catalog_id?: string | null;
  model_description?: string;
  background?: string;
  extra?: string;
  steps?: number;
  guidance?: number;
  seed?: number;
}) {
  return apiPost<ImageJob[]>('/api/product/generate', body);
}

export async function exportImages(job_ids: string[], dest_dir: string, prefix = '') {
  return apiPost<{ written: string[]; dir: string }>('/api/image/export', { job_ids, dest_dir, prefix });
}

export async function listCharacters() {
  return api<Character[]>('/api/characters');
}

export async function saveCharacter(body: {
  name: string;
  description?: string;
  tags?: string[];
  reference_path?: string | null;
  slug?: string | null;
}) {
  return apiPost<Character>('/api/characters', body);
}

export async function deleteCharacter(slug: string) {
  const resp = await fetch(`${await baseUrl()}/api/characters/${slug}`, {
    method: 'DELETE', headers: await authHeaders(),
  });
  if (!resp.ok) throw new Error(`Delete failed: ${resp.status}`);
  return resp.json();
}

export async function characterReferenceUrl(slug: string): Promise<string> {
  const resp = await fetch(`${await baseUrl()}/api/characters/${slug}/reference`, {
    headers: await authHeaders(),
  });
  if (!resp.ok) throw new Error('No reference');
  return URL.createObjectURL(await resp.blob());
}

export async function fetchImageBlobUrl(id: string): Promise<string> {
  const url = `${await baseUrl()}/api/image/output/${id}`;
  const resp = await fetch(url, { headers: await authHeaders() });
  if (!resp.ok) throw new Error(`Failed to fetch image: ${resp.status}`);
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

export interface MusicOptions {
  sample_rates: number[];
  bit_depths: number[];
  stems: string[];
  formats: string[];
  quality: Record<string, number>;
  installed: boolean;
  max_duration: number;
}

export interface NarrationVoice {
  slug: string;
  name: string;
  kind: 'preset' | 'cloned';
  has_sample: boolean;
  notes: string;
}

export interface NarrationEngineInfo {
  id: string;
  label: string;
  note: string;
  voice_kind: string;
  installed: boolean;
}

export interface NarrationOptions {
  sample_rates: number[];
  bit_depths: number[];
  formats: string[];
  quality: Record<string, number>;
  installed: boolean;
  engines: NarrationEngineInfo[];
  voices: NarrationVoice[];
}

export interface NarrationJob {
  id: string;
  status: 'pending' | 'running' | 'done' | 'error';
  stage: string;
  chars: number;
  output_path: string | null;
  duration_s: number;
  done: boolean;
  error: string | null;
}

export async function getNarrationOptions(engine = 'realtime') {
  return api<NarrationOptions>(`/api/narration/options?engine=${encodeURIComponent(engine)}`);
}

export async function generateNarration(body: {
  model_dir: string;
  text: string;
  voice_slug?: string;
  sample_rate?: number;
  bit_depth?: number;
  audio_format?: string;
  cfg_scale?: number;
  ddpm_steps?: number;
  engine?: string;
}) {
  return apiPost<NarrationJob>('/api/narration/generate', body);
}

export async function getNarrationJob(id: string) {
  return api<NarrationJob>(`/api/narration/jobs/${id}`);
}

export async function narrationAudioUrl(id: string): Promise<string> {
  const resp = await fetch(`${await baseUrl()}/api/narration/audio/${id}`, {
    headers: await authHeaders(),
  });
  if (!resp.ok) throw new Error(`Audio not ready: ${resp.status}`);
  return URL.createObjectURL(await resp.blob());
}

export interface MusicJob {
  id: string;
  prompt: string;
  status: 'pending' | 'running' | 'separating' | 'done' | 'error';
  stage: string;
  output_path: string | null;
  stems: Record<string, string>;
  duration: number;
  done: boolean;
  error: string | null;
}

export async function getMusicOptions() {
  return api<MusicOptions>('/api/music/options');
}

export async function generateMusic(body: {
  model_dir: string;
  prompt: string;
  lyrics?: string;
  instrumental?: boolean;
  duration?: number;
  bpm?: number | null;
  keyscale?: string;
  steps?: number;
  guidance?: number;
  seed?: number | null;
  sample_rate?: number;
  bit_depth?: number;
  separate_stems?: boolean;
}) {
  return apiPost<MusicJob>('/api/music/generate', body);
}

export async function getMusicJob(id: string) {
  return api<MusicJob>(`/api/music/jobs/${id}`);
}

export async function musicAudioUrl(id: string, stem = ''): Promise<string> {
  const q = stem ? `?stem=${encodeURIComponent(stem)}` : '';
  const resp = await fetch(`${await baseUrl()}/api/music/audio/${id}${q}`, {
    headers: await authHeaders(),
  });
  if (!resp.ok) throw new Error(`Audio not ready: ${resp.status}`);
  return URL.createObjectURL(await resp.blob());
}

export async function transcribeAudio(modelPath: string, blob: Blob, filename = 'audio.webm'): Promise<string> {
  const form = new FormData();
  form.append('file', blob, filename);
  form.append('model_path', modelPath);
  const url = `${await baseUrl()}/api/voice/transcribe`;
  const resp = await fetch(url, { method: 'POST', headers: await authHeaders(), body: form });
  if (!resp.ok) throw new Error(`Transcription failed: ${resp.status}`);
  const data = await resp.json();
  return data.text as string;
}

export async function speakText(text: string, voice = 'af_heart', speed = 1.0): Promise<string> {
  const url = `${await baseUrl()}/api/voice/speak`;
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' };
  const resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ text, voice, speed }) });
  if (!resp.ok) throw new Error(`Speech synthesis failed: ${resp.status}`);
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

export async function listVoices() {
  return api<string[]>('/api/voice/voices');
}

export async function agentSocket(): Promise<WebSocket> {
  const { port, token } = await getSidecarInfo();
  return new WebSocket(`ws://127.0.0.1:${port}/ws/agent?token=${token}`);
}

// ------------------------------------------------------------ runtime setup

/**
 * Observable state of the Python engine. The window opens whether or not the
 * engine is running, so the setup screen can explain which piece is missing
 * rather than the app failing to start.
 */
export interface RuntimeStatus {
  running: boolean;
  source_ready: boolean;
  uv_found: boolean;
  deps_ready: boolean;
  engine_dir: string;
  error: string | null;
}

export async function runtimeStatus(): Promise<RuntimeStatus> {
  return invoke<RuntimeStatus>('runtime_status');
}

/** Creates the environment and installs dependencies. Progress arrives as
 *  `engine-install-log` events rather than in the return value. */
export async function installRuntime(): Promise<void> {
  await invoke('install_runtime');
}

export async function startRuntime(): Promise<SidecarInfo> {
  const info = await invoke<SidecarInfo>('start_runtime');
  cached = info; // so the first api() call after setup doesn't re-poll
  return info;
}

export async function setKeepAwake(enabled: boolean) {
  return apiPost('/api/settings/keep_awake', { enabled });
}

export interface ToolGroup {
  id: string;
  label: string;
  note: string;
  count: number;
}

export interface AgentTools {
  groups: ToolGroup[];
  /** null means the set is chosen automatically from the loaded model's size. */
  configured: string[] | null;
  resolved: string[];
  active_count: number;
}

export async function getAgentTools() {
  return api<AgentTools>('/api/agent/tools');
}

export async function setAgentToolGroups(groups: string[] | null) {
  return apiPost('/api/agent/tool_groups', { groups });
}
