import { invoke } from '@tauri-apps/api/core';
import { ThinkingSplitter } from './thinking';

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
  output_dir: string;
  output_dir_is_default: boolean;
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
  /** Settings the model asks for — a distilled checkpoint wants very few steps.
   *  Optional: views also build LocalModel values of their own. */
  defaults?: { steps?: number; guidance?: number };
  /** For MLX models found on disk rather than in the catalog: which mflux
   *  entry point runs it, and which base model to configure it as. */
  mflux_cli?: string | null;
  mflux_base?: string | null;
  /** Adapters applied on load — a fine-tune without a second copy of the weights. */
  lora_paths?: string[];
  lora_scales?: number[];
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
  /** Whether the loaded model has an image encoder. A text-only model has no
   *  way to receive pixels, so attaching one has to be refused rather than
   *  accepted and silently ignored. */
  supports_vision?: boolean;
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
  /** A reasoning model's working, streamed before the answer. */
  reasoning?: string;
  /** Pictures attached to this turn, as data URLs. Held beside the text
   *  rather than inside it so the conversation stays readable, the thumbnails
   *  can be shown, and the wire format is built at send time. */
  images?: string[];
  /** Thumbnails the model asked to show from the web. Shown to the reader and
   *  never sent back to the model — it cannot see them, and describing them to
   *  it as though it could is how a model ends up discussing a picture it has
   *  no access to. */
  found?: WebImage[];
}

// ------------------------------------------------------------ conversations

export interface ConversationSummary {
  id: string;
  title: string;
  created: number;
  updated: number;
  messages: number;
  model_path?: string | null;
}

export interface Conversation extends Omit<ConversationSummary, 'messages'> {
  messages: ChatMessage[];
}

export interface ConversationList {
  conversations: ConversationSummary[];
  /** Files that exist and could not be decrypted. Shown rather than hidden:
   *  it is the only symptom of a key that changed. */
  unreadable: number;
  /** Whether the key is in the OS keychain rather than a file beside the data. */
  secure: boolean;
  backend: string;
}

export async function listConversations() {
  return api<ConversationList>('/api/conversations');
}

export async function readConversation(id: string) {
  return api<Conversation>(`/api/conversations/${id}`);
}

export async function writeConversation(
  id: string,
  body: { messages: ChatMessage[]; title?: string; model_path?: string | null },
) {
  return api<Conversation>(`/api/conversations/${id}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function deleteConversation(id: string) {
  return api<{ deleted: boolean }>(`/api/conversations/${id}`, { method: 'DELETE' });
}

/** A streamed chunk: the answer itself, or the model thinking out loud. */
export interface ChatChunk {
  kind: 'text' | 'thinking';
  text: string;
}

/** The wire form of a turn.
 *
 *  A message with pictures becomes the content ARRAY that vision models
 *  expect; one without stays a plain string, because a text-only server given
 *  an array of one text part will often reject it outright. `reasoning` and
 *  `images` are ours and are dropped here — sending them back would put the
 *  model's own working into its next prompt as though the user had said it.
 */
export function wireMessage(message: ChatMessage) {
  if (!message.images?.length) {
    return { role: message.role, content: message.content };
  }
  return {
    role: message.role,
    content: [
      { type: 'text', text: message.content },
      ...message.images.map((url) => ({ type: 'image_url', image_url: { url } })),
    ],
  };
}

export async function* streamChat(
  messages: ChatMessage[], signal?: AbortSignal,
): AsyncGenerator<ChatChunk> {
  const url = `${await baseUrl()}/api/chat`;
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' };
  const resp = await fetch(url, {
    method: 'POST', headers,
    body: JSON.stringify({ messages: messages.map(wireMessage) }), signal,
  });
  if (!resp.ok || !resp.body) throw new Error(`Chat failed: ${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  // Some models write their reasoning into the answer as <think> tags rather
  // than into `reasoning_content`. Unsplit, the reader gets several paragraphs
  // of the model talking to itself — in which it may contradict the answer
  // that follows — before reaching the answer.
  const splitter = new ThinkingSplitter();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      // Anything the splitter was holding back — a reply that ended on a
      // dangling angle bracket, or mid-thought — belongs to the user.
      if (data === '[DONE]') { yield* splitter.flush(); return; }
      try {
        const json = JSON.parse(data);
        const d = json.choices?.[0]?.delta;
        // Reasoning models put most of their output here and only then produce
        // an answer. Dropping it meant the UI sat blank through a couple of
        // hundred tokens and looked like it had hung.
        const thinking = d?.reasoning_content ?? d?.reasoning;
        if (thinking) yield { kind: 'thinking', text: thinking };
        if (d?.content) yield* splitter.push(d.content);
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
  /** Where the finished file landed, for Save / Save as / Reveal. */
  output_path: string | null;
}

export interface ImageGenerateOptions {
  negative_prompt?: string;
  /** Uncensored text encoder, for pipelines whose encoder is a causal LM. */
  text_encoder_path?: string;
  mflux_cli?: string;
  mflux_base?: string;
  lora_paths?: string[];
  lora_scales?: number[];
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

// ------------------------------------------------------- inline chat images

/**
 * How a chat model asks for a picture. A plain text marker rather than
 * function calling, because the small local models this app is built for
 * support it unevenly, and a marker works with every one of them.
 */
export const IMAGE_MARKER = /\[\[image:\s*([^\]\n]{3,400})\]\]/gi;

export async function webSearch(query: string) {
  return apiPost<{ results: string }>('/api/web/search', { query });
}

export async function webRead(url: string) {
  return apiPost<{ text: string }>('/api/web/read', { url });
}

export interface WebImage {
  /** Served by the search engine, not the origin site — so showing one does
   *  not announce the user to whichever site happens to host the picture. */
  thumbnail: string;
  source: string;
  title: string;
}

export async function webImages(query: string) {
  return apiPost<{ images: WebImage[] }>('/api/web/images', { query });
}

/** What the model is told before anything the user says.
 *
 *  Built per turn rather than fixed, because the most useful thing in it is
 *  the date. A model with no idea what today is cannot tell that its own
 *  training is two years stale — asked about anything current it answers
 *  confidently from memory, because from the inside there is nothing to
 *  suggest otherwise. Told the date, the same weights hedge, and reach for a
 *  search.
 *
 *  ORDER MATTERS, more than it should. A small model treats the first
 *  instruction as the loudest, and this prompt used to open with "You can show
 *  a picture" — so it drew one for nearly every reply, including questions
 *  about episode numbers where a picture answers nothing. "Use it sparingly"
 *  was one clause against three sentences of encouragement, and it lost.
 *  Answering comes first now, and the picture capability comes last and is
 *  only mentioned when it is switched on.
 */
export function chatSystemPrompt(
  { now = new Date(), pictures = false, web = true }:
    { now?: Date; pictures?: boolean; web?: boolean } = {},
): string {
  const today = now.toLocaleDateString(undefined, {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });

  const parts = [
    `Today is ${today}. The user is on a Mac, running Uncloud, which keeps `
    + 'everything local. Your training finished well before today — assume '
    + 'anything time-sensitive you remember is out of date, and check rather '
    + 'than guess.',

    'Answer directly and finish your answer in this turn. Never narrate that '
    + 'you are waiting, preparing, or about to answer.',

  ];

  // Described only when it is switched on, and its ABSENCE described when it
  // is off — a model that does not know it is offline answers questions about
  // the present from memory in the same confident voice it uses for
  // arithmetic, which is how the iOS answer happened.
  if (web) {
    parts.push(
    // The web, through the same written-marker mechanism as the image preview.
    // Not a tool-calling protocol: local servers vary in whether they support
    // one, and a feature that works on a third of the models a customer might
    // install is worse than one that works everywhere.
    'You can look things up on the web. To search, write [[search: your query]] '
    + 'on its own line. To read a specific page, write [[read: https://…]] on '
    + 'its own line. Then STOP and write nothing else — the results are fetched '
    + 'and given to you, and you answer in the next turn.\n'
    + 'Look something up whenever the answer depends on current information: '
    + 'anything recent, any release or version, prices, news, dates, or '
    + 'anything you are unsure about. Your training has a cutoff and the world '
    + 'has moved since; guessing from memory about something current is the '
    + 'main way you will be wrong. This includes questions about films, books '
    + 'and television — episode numbers and titles are exactly the kind of '
    + 'detail that is easy to reconstruct wrongly and easy to check.\n'
    + 'When you answer from what was fetched, say so. When you answer from '
    + 'memory about something that may have changed, say that too.',
    );
  } else {
    parts.push(
      'You have no internet access in this conversation and cannot look '
      + 'anything up. If the user asks you to check something online, say '
      + 'plainly that you cannot — they can switch the web on beside the '
      + 'message box, or use Chisel. Answer from what you know, and say when '
      + 'it may be out of date. Never imply you have checked anything.',
    );
  }

  //: Only described when the user has asked for it. A capability a model is
  //  told about is a capability it will use, so the reliable way not to get a
  //  picture with every reply is not to mention pictures.
  if (pictures) {
    parts.push(
      'You may add a picture, but the default is not to. Most answers are '
      + 'better without one, and a picture that merely decorates an answer '
      + 'wastes the reader\'s time and several seconds of their machine.\n'
      + 'To show real photographs — a place, a person, a product, a real scene '
      + '— write [[pictures: what to show]] on its own line; thumbnails from '
      + 'the web are placed there.\n'
      + 'To draw something that does not exist — a diagram, a sketch, an '
      + 'invented scene — write [[image: a detailed description]] on its own '
      + 'line.\n'
      + 'Do neither when the question is about a fact, a number, a name, a '
      + 'date, an episode, code, or anything a sentence answers. Ask yourself '
      + 'whether the reader would be worse off without it; if not, leave it '
      + 'out.',
    );
  }

  return parts.join('\n\n');
}

/**
 * A fast, deliberately low-fidelity render for thinking with, not a finished
 * picture: few steps at 512px so it arrives in seconds rather than minutes.
 */
export async function quickImagePreview(prompt: string): Promise<string> {
  const models = await getLibrary();
  const img = models.find((m) => m.category === 'image' && m.ready);
  if (!img) throw new Error('No image model installed');

  const job = await generateImage(img.path, img.engine, prompt, img.catalog_id, {
    steps: 6,
    width: 512,
    height: 512,
    // Which mflux entry point runs this checkpoint, and which base to
    // configure it as. Omitting them fell back to the FLUX.1 default, so every
    // FLUX.2 model failed here looking for `text_encoder_2` — a component
    // FLUX.1 has and FLUX.2 does not. The Image tab always passed these; this
    // path never did, so the same model worked there and failed here.
    mflux_cli: img.mflux_cli ?? undefined,
    mflux_base: img.mflux_base ?? undefined,
  });

  for (let i = 0; i < 900; i++) {
    const j = await getImageJob(job.id);
    if (j.done) {
      if (j.status === 'error') throw new Error(j.error || 'Generation failed');
      return fetchImageBlobUrl(job.id);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error('Image generation timed out');
}

// -------------------------------------------------------------------- video

export interface VideoJob {
  id: string;
  prompt: string;
  status: 'pending' | 'running' | 'done' | 'error';
  stage: string;
  step: number;
  total_steps: number;
  output_path: string | null;
  error: string | null;
  done: boolean;
}

export interface VideoOptions {
  default_frames: number;
  default_fps: number;
  default_width: number;
  default_height: number;
  default_steps: number;
  default_guidance: number;
  default_negative_prompt: string;
  max_pixels: number;
}

export interface VideoGenerateOptions {
  negative_prompt?: string;
  frames?: number;
  fps?: number;
  width?: number;
  height?: number;
  steps?: number;
  guidance?: number;
  seed?: number;
}

export async function getVideoOptions() {
  return api<VideoOptions>('/api/video/options');
}

export async function generateVideo(
  model_path: string, prompt: string, opts: VideoGenerateOptions = {},
) {
  return apiPost<VideoJob>('/api/video/generate', { model_path, prompt, ...opts });
}

export async function getVideoJob(id: string) {
  return api<VideoJob>(`/api/video/jobs/${id}`);
}

export async function fetchVideoBlobUrl(id: string): Promise<string> {
  const resp = await fetch(`${await baseUrl()}/api/video/output/${id}`, {
    headers: await authHeaders(),
  });
  if (!resp.ok) throw new Error(`Failed to fetch video: ${resp.status}`);
  return URL.createObjectURL(await resp.blob());
}

export async function setOutputDir(path: string) {
  return apiPost<{ ok: boolean; output_dir: string }>('/api/settings/output_dir', { path });
}

// ------------------------------------------------------------ model memory

// ---------------------------------------------------------------- quantise
export interface QuantizeBase { id: string; repo: string; cli: string }

export interface QuantizeJob {
  id: string;
  name: string;
  dest: string;
  status: 'running' | 'done' | 'error';
  stage: string;
  error: string | null;
  done: boolean;
  size_gb: number;
  log: string[];
}

export async function getQuantizeBases() {
  return api<{ bits: number[]; bases: QuantizeBase[] }>('/api/quantize/bases');
}
export async function listQuantizeJobs() {
  return api<QuantizeJob[]>('/api/quantize');
}
export async function startQuantize(body: {
  source: string; base: string; name: string;
  transformer_bits: number; encoder_bits: number;
  lora_paths?: string[]; lora_scales?: number[];
}) {
  return apiPost<QuantizeJob>('/api/quantize', body);
}

export interface MemoryBudget {
  budget: {
    total_gb: number; available_gb: number; device: string;
    budget_gb: number; unified: boolean; platform: string;
  };
  estimate?: { tokens: number; weights_gb: number; sequence_gb: number; total_gb: number };
  fits?: boolean;
  tight?: boolean;
  /** Whether this machine can run video at all, independent of the job asked
   *  for. Below the floor every setting fails identically, which reads as a
   *  broken feature rather than a machine that is too small. */
  video?: {
    runnable: boolean;
    budget_gb: number;
    weights_gb?: number;
    reason?: string;
    longest_frames_at_min_size?: number;
    largest_size_at_min_frames?: [number, number];
  };
}

/** What a job will cost against what the machine can give. Asked before
 *  starting: an oversized job is refused on macOS but can take a Linux box
 *  with a discrete GPU down with it. */
export async function getBudget(p?: {
  frames: number; width: number; height: number; model_path?: string;
}) {
  // Send the path, not a size: the engine works out what stays resident, which
  // for video is a fraction of the folder — the text encoder is freed first.
  const q = p ? `?${new URLSearchParams({
    frames: String(p.frames), width: String(p.width), height: String(p.height),
    ...(p.model_path ? { model_path: p.model_path } : {}),
  })}` : '';
  return api<MemoryBudget>(`/api/system/budget${q}`);
}

export async function getWeightCache() {
  return api<{ bytes: number; path: string }>('/api/system/weight_cache');
}
export async function clearWeightCache() {
  return apiPost<{ freed_bytes: number }>('/api/system/weight_cache/clear');
}

export interface ResidentModels {
  text_model: string | null;
  image_pipeline: string | null;
  mflux_model: string | null;
  flux2_profile: string | null;
  video_pipeline: string | null;
  anything: boolean;
}

export async function getResident() {
  return api<ResidentModels>('/api/system/resident');
}

export async function stopAllModels() {
  return apiPost<Record<string, boolean>>('/api/system/stop_all');
}

// ------------------------------------------------------------------ outputs

export interface OutputFile {
  path: string;
  name: string;
  relative: string;
  kind: 'image' | 'video' | 'audio' | 'other';
  group: string;
  size_bytes: number;
  modified: number;
  age_seconds: number;
}

export async function listOutputs(kind = '', limit = 300) {
  const q = new URLSearchParams({ limit: String(limit), ...(kind ? { kind } : {}) });
  return api<{ root: string; files: OutputFile[] }>(`/api/outputs?${q}`);
}

/** Blob URL for an output file — the engine requires a bearer token, so an
 *  <img src> pointing at the endpoint directly would 401. */
export async function outputBlobUrl(path: string): Promise<string> {
  const url = `${await baseUrl()}/api/outputs/file?path=${encodeURIComponent(path)}`;
  const resp = await fetch(url, { headers: await authHeaders() });
  if (!resp.ok) throw new Error(`Could not load ${path}`);
  return URL.createObjectURL(await resp.blob());
}

export async function revealOutput(path: string) {
  return apiPost<{ ok: boolean }>('/api/outputs/reveal', { path });
}

export async function deleteOutput(path: string) {
  return apiPost<{ ok: boolean }>('/api/outputs/delete', { path });
}

/** Copy a generated file out to somewhere the user picked. `dest` is a folder
 *  when `into_folder`, otherwise the full filename a save dialog returned. */
export async function saveCopy(path: string, dest: string, into_folder: boolean) {
  return apiPost<{ path: string }>('/api/outputs/save_copy', { path, dest, into_folder });
}
