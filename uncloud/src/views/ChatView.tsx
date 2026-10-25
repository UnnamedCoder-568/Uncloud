import InferenceControls from '../components/InferenceControls';
import { useInference } from '../lib/inference';
import AutoGrowTextarea from "../components/AutoGrowTextarea";
import { useDismiss } from '../lib/useDismiss';
import ActivityOrb from '../components/ActivityOrb';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ArrowUp, Square, Mic, Volume2, VolumeX, Hammer, PanelRight, Plus, X, Globe,
  Image as ImageIcon, ImageOff, GlobeLock, AudioLines, MessagesSquare,
  Settings2, Paperclip, FileText, Copy, Check, NotebookPen } from 'lucide-react';
import { TitleBarPortal } from '../components/TitleBar';
import { Mark } from '../components/Wordmark';
import Markdown from '../components/Markdown';
import { fromConversation, sendToChisel } from '../lib/handoff';
import Conversations from '../components/Conversations';
import { usePaneVisible, useWhenVisible } from '../components/Panes';
import ReplyVoice from '../components/ReplyVoice';
import AddFromDisk from '../components/AddFromDisk';
import { useLibraryVersion } from '../lib/library-changed';
import { splitThinking } from '../lib/thinking';
import { Sentences, useTalk } from '../lib/useTalk';
import { cleanReply } from '../lib/reply';
import { LookupSession, describe, findLookups, initialWebLookup, lookupKey, wantsPictures, resultsTurn, stripLookups } from '../lib/lookup';
import { lookupForTool } from '../lib/native-tools';
import { chartReply, readBarChart, type BarChartData } from '../lib/bar-chart';
import { compactAvailable, contextMessages } from '../lib/context';
import { fitToolContext, fitWebContext } from '../lib/web-context';
import { prepareConversation, type Continuity } from '../lib/dynamic-context';
import { historyQuery, searchHistory } from '../lib/history';
import { printerSound } from '../lib/printer-sound';
import { apiPost, getLibrary, getAdapters, startEngine, engineStatus, streamChat, countChatContext, transcribeAudio, speakReply, IMAGE_MARKER, chatSystemPrompt, parseReplyImages, generateReplyImage,
  listConversations, readConversation, writeConversation, deleteConversation,
  webSearch, webRead, webImages, MANNERS, getPermissions, setPermission,
  outputBlobUrl, revealOutput, uploadChatAttachment, saveNote as saveReplyNote,
  listNotes, deleteNote } from '../lib/sidecar';
import type { AdapterCard, ChatContextUsage, LocalModel, ChatMessage, ChatToolCall, ChatAttachment, ConversationList, SavedNote, WebImage, PersonaSnapshot } from '../lib/sidecar';

/** A conversation id: sixteen hex characters, which is what the engine accepts
 *  as a filename. `crypto.randomUUID` needs a secure context and is not
 *  guaranteed everywhere this window can run; `getRandomValues` is, and a
 *  silent failure here would be a conversation that never saves. */
function newConversationId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export default function ChatView({ persona }: { persona?: PersonaSnapshot } = {}) {
  const visible = usePaneVisible();
  const [sessionPersona, setSessionPersona] = useState(persona);
  const [networkDenied, setNetworkDenied] = useState(false);
  const [networkError, setNetworkError] = useState('');
  const [models, setModels] = useState<LocalModel[]>([]);
  const [activeModel, setActiveModel] = useState<LocalModel | null>(null);
  const [adapters, setAdapters] = useState<AdapterCard[]>([]);
  const [activeAdapter, setActiveAdapter] = useState<string | null>(null);
  const [loadingModel, setLoadingModel] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useDismiss(pickerOpen, () => setPickerOpen(false));
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [contextUsage, setContextUsage] = useState<ChatContextUsage | null>(null);
  const [compactSummary, setCompactSummary] = useState('');
  const [compactedThrough, setCompactedThrough] = useState(0);
  const [compacting, setCompacting] = useState(false);
  const [contextNotice, setContextNotice] = useState('');
  const compactAbort = useRef<AbortController | null>(null);
  const [contextLength, setContextLength] = useState('');
  const [loadedContext, setLoadedContext] = useState<{
    context_limit?: number; context_profile?: { native_limit: number | null } }>({});
  const [contextWindows, setContextWindows] = useState<Record<string, number>>(() => {
    try { return JSON.parse(localStorage.getItem('uncloud.chat.contextWindows') || '{}'); }
    catch { return {}; }
  });
  const initialContextWindows = useRef(contextWindows);
  const [rawMode] = useState(() => localStorage.getItem('uncloud.debug.raw') === 'on');
  //: Which saved conversation this is. Made on the first send rather than on
  //  arrival, so opening Chat and changing your mind does not litter the list
  //  with empty conversations.
  const [conversationId, setConversationId] = useState<string | null>(null);
  const inference = useInference(activeModel?.path, conversationId, true);
  const systemPrompt = useCallback((options: Parameters<typeof chatSystemPrompt>[0]) =>
    [sessionPersona?.instructions ?? '', typeof inference.values.system_prompt === 'string' ? inference.values.system_prompt : '',
      chatSystemPrompt(options)].filter(Boolean).join('\n\n'),
    [inference.values.system_prompt, sessionPersona?.instructions]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [notes, setNotes] = useState<SavedNote[]>([]);
  const [saved, setSaved] = useState<ConversationList | null>(null);
  //: Pictures staged for the next message. Data URLs, so a file the user
  //  moves or deletes afterwards does not empty the conversation later.
  const [attached, setAttached] = useState<string[]>([]);
  const [attachedFiles, setAttachedFiles] = useState<ChatAttachment[]>([]);
  const [attachingFile, setAttachingFile] = useState(false);
  const [visionOk, setVisionOk] = useState(false);
  //: What is being fetched right now, and what has been. A conversation that
  //  reaches the internet has to say so while it happens — this is the one
  //  thing in an otherwise offline application that leaves the machine.
  const [looking, setLooking] = useState<string[]>([]);
  const [consulted, setConsulted] = useState<string[]>([]);
  const [input, setInput] = useState('');
  const [generating, setGenerating] = useState(false);
  const chatAbort = useRef<AbortController | null>(null);
  // Every async continuation proves it still belongs to the conversation on
  // screen. This is the fence that stops an old reply landing in a newly
  // opened chat after navigation or a slow LAN reconnect.
  const generationEpoch = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
  const libraryVersion = useLibraryVersion();
  const sttRef = useRef<LocalModel | null>(null);
  useEffect(() => { sttRef.current = sttModel; }, [sttModel]);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(false);
  //: Whether replies may include pictures. Off by default: an image on every
  //  answer costs seconds of the machine per message and answers nothing that
  //  a sentence did not. Remembered, because it is a preference about how
  //  replies read rather than a property of one message.
  const [pictures, setPictures] = useState(() => {
    try { return localStorage.getItem('uncloud.chat.pictures') === 'on'; }
    catch { return false; }
  });
  //: Whether this conversation may reach the internet. On by default because
  //  a model that cannot check anything answers questions about the present
  //  from a memory years out of date — but SWITCHABLE, and visible, because
  //  this is the one thing in an otherwise local application that sends the
  //  user's words to somebody else's server.
  //: Which voice reads replies, and in what manner. Remembered: both are
  //  preferences about how the assistant sounds, not properties of a message.
  const [voice, setVoice] = useState(() => {
    try { return localStorage.getItem('uncloud.chat.voice') || 'bm_george'; }
    catch { return 'bm_george'; }
  });
  const [manner, setManner] = useState(() => {
    try { return localStorage.getItem('uncloud.chat.manner') || 'plain'; }
    catch { return 'plain'; }
  });
  useEffect(() => {
    try {
      localStorage.setItem('uncloud.chat.voice', voice);
      localStorage.setItem('uncloud.chat.manner', manner);
    } catch { /* a browser refusing storage is not worth an error */ }
  }, [voice, manner]);

  //: The loop is built once and lives across renders, while `send` closes over
  //  state that changes every keystroke. The ref is what keeps the loop calling
  //  the CURRENT send rather than the one that existed when it started.
  const sendRef = useRef<(text: string, speak: boolean,
                          say?: (sentence: string) => void) => Promise<void>>(
    async () => {});
  //: The conversation loop has no transcript of its own to fail into — a
  //  microphone that was refused has to say so somewhere.
  const [lastError, setLastError] = useState<string | null>(null);
  const [copiedReply, setCopiedReply] = useState<number | null>(null);
  const [notedReply, setNotedReply] = useState<number | null>(null);

  async function copyReply(index: number, content: string, verbatim = false) {
    try {
      await navigator.clipboard.writeText(verbatim ? content : cleanReply(content));
      setCopiedReply(index);
      setTimeout(() => setCopiedReply((current) => current === index ? null : current), 1400);
    } catch { /* selectable text remains available */ }
  }

  async function noteReply(index: number, content: string) {
    const value = cleanReply(content);
    if (!value) return;
    const firstLine = value.split('\n').find((line) => line.trim())?.trim() || 'Reply';
    const key = `${firstLine.slice(0, 72)} · ${new Date().toLocaleString()}`;
    try {
      await saveReplyNote(key, value);
      setNotes(await listNotes().catch(() => notes));
      setNotedReply(index);
      setTimeout(() => setNotedReply((current) => current === index ? null : current), 1800);
    } catch (error) {
      setLastError(String(error).replace(/^Error:\s*/, ''));
    }
  }

  const [web, setWeb] = useState(() => {
    try { return localStorage.getItem('uncloud.chat.web') !== 'off'; }
    catch { return true; }
  });
  const nativeToolsAvailable = !rawMode
    && inference.info?.active?.model_path === activeModel?.path
    && inference.info?.active?.profile.capabilities.native_tools === true;
  const nativeWeb = web && nativeToolsAvailable;
  useEffect(() => {
    try { localStorage.setItem('uncloud.chat.web', web ? 'on' : 'off'); }
    catch { /* a browser refusing storage is not worth an error */ }
  }, [web]);
  useEffect(() => {
    try { localStorage.setItem('uncloud.chat.pictures', pictures ? 'on' : 'off'); }
    catch { /* a browser refusing storage is not worth an error */ }
  }, [pictures]);
  const [speaking, setSpeaking] = useState(false);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    getLibrary().then((list) => {
      setModels(list.filter((m) => m.category === 'text' && m.ready));
      const stt = list.find((m) => m.category === 'voice-stt' && m.ready);
      if (stt) setSttModel(stt);
    });
  }, [libraryVersion]);

  useEffect(() => {
    if (pickerOpen) getAdapters().then(setAdapters).catch(() => setAdapters([]));
  }, [pickerOpen]);

  useEffect(() => {
    engineStatus().then((s) => {
      setLoadedContext(s);
      if (s.running && s.model_path) {
        setContextLength(initialContextWindows.current[s.model_path]?.toString() ?? '');
        setActiveAdapter(s.adapter_path ?? null);
        setActiveModel((prev) => prev ?? {
          id: s.model_path!, name: s.model_path!.split('/').pop()!, category: 'text',
          engine: s.engine!, path: s.model_path!, size_gb: 0, catalog_id: null,
          tags: [], ready: true, note: null, capabilities: ['text2img'],
        });
      }
    });
  }, []);

  useWhenVisible(() => {
    void engineStatus().then(status => {
      setLoadedContext(status);
      if (!status.running || !status.model_path) { setActiveModel(null); return; }
      setContextLength(contextWindows[status.model_path]?.toString() ?? '');
      setActiveAdapter(status.adapter_path ?? null);
      setActiveModel(models.find(m => m.path === status.model_path) ?? {
        id: status.model_path, name: status.model_path.split('/').pop()!, category: 'text',
        engine: status.engine!, path: status.model_path, size_gb: 0, catalog_id: null,
        tags: [], ready: true, note: null, capabilities: [],
      });
      void inference.refresh();
    }).catch(() => {});
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function selectModel(model: LocalModel, adapter: AdapterCard | null = null) {
    if (loadingModel) return;
    chatAbort.current?.abort();
    compactAbort.current?.abort();
    setPickerOpen(false);
    setLoadingModel(true);
    try {
      const status = await startEngine(
        model.path, model.engine, adapter?.path, contextWindows[model.path]);
      setLoadedContext(status);
      setContextLength(contextWindows[model.path]?.toString() ?? '');
      setActiveModel(model);
      setActiveAdapter(adapter?.path ?? null);
      await inference.refresh();
    } catch (e) {
      alert(`Failed to load model: ${e}`);
    } finally {
      setLoadingModel(false);
    }
  }

  // Keyed by message index. A reply can ask for more than one picture, but not
  // many — each costs a diffusion run and evicts the chat model from memory.
  const [previews, setPreviews] = useState<
    Record<number, { prompt: string; url?: string; error?: string }[]>
  >({});

  /** Load an image the conversation already recorded.
   *
   *  Reopening a conversation goes through here, so a picture made yesterday
   *  reappears rather than the message looking like it never had one.
   */
  const loadDrawn = useCallback(async (turns: ChatMessage[]) => {
    const restored: Record<number, { prompt: string; url?: string; error?: string }[]> = {};
    await Promise.all(turns.map(async (m, i) => {
      if (!m.drew?.length) return;
      restored[i] = await Promise.all(m.drew.map(async (d) => {
        try {
          return { prompt: d.prompt, url: await outputBlobUrl(d.path) };
        } catch {
          // Deleted from Outputs, or the drive is not mounted. Saying so is
          // better than a broken image icon with no explanation.
          return { prompt: d.prompt, error: 'This picture is no longer on disk.' };
        }
      }));
    }));
    setPreviews(restored);
  }, []);

  async function renderPreviews(
    index: number, reply: string, epoch: number, savedConversationId: string,
  ) {
    // The switch holds regardless of what the model wrote. A model told not to
    // draw will still occasionally draw, and the user's setting has to win
    // that argument rather than merely take part in it.
    if (!pictures || epoch !== generationEpoch.current) return;
    const requests = parseReplyImages(reply);
    if (!requests.length) return;
    setPreviews((p) => ({
      ...p,
      [index]: requests.map((request) => ({ prompt: request.prompt })),
    }));
    for (let i = 0; i < requests.length; i++) {
      const request = requests[i];
      try {
        const { url, path } = await generateReplyImage(request);
        if (epoch !== generationEpoch.current) continue;
        setPreviews((p) => {
          const row = [...(p[index] || [])];
          row[i] = { ...row[i], url };
          return { ...p, [index]: row };
        });
        // Recorded on the message and saved, so the picture is still there
        // tomorrow. Previously this lived only in view state and every
        // reopened conversation lost every picture in it.
        if (path) {
          setMessages((m) => {
            const copy = [...m];
            const turn = copy[index];
            if (!turn) return m;
            copy[index] = {
              ...turn,
              drew: [...(turn.drew ?? []), { prompt: request.prompt, path }],
            };
            void persist(savedConversationId, copy);
            return copy;
          });
        }
      } catch (e) {
        if (epoch !== generationEpoch.current) continue;
        setPreviews((p) => {
          const row = [...(p[index] || [])];
          row[i] = { ...row[i], error: String(e).replace(/^Error:\s*/, '') };
          return { ...p, [index]: row };
        });
      }
    }
  }

  /** Start or stop hands-free conversation.
   *
   *  Speaking is forced on while it runs — a conversation where the reply is
   *  only written is not a conversation, and having to notice a separate
   *  toggle to hear it would be a trap.
   */
  //: Hands-free, on the shared loop: natively where this Mac can listen for
  //  itself, and through a speech model everywhere else. Each sentence of the
  //  reply is spoken as it is written rather than the whole answer at the end.
  const talk = useTalk(voice, async (said, say) => {
    await sendRef.current(said, true, say);
  });

  const toggleConversation = useCallback(() => {
    // Speaking is forced on while it runs — a conversation whose reply is only
    // written is not a conversation, and a separate toggle to hear it would be
    // a trap.
    if (!talk.active) setAutoSpeak(true);
    talk.toggle();
  }, [talk]);

  useEffect(() => { sendRef.current = send; });

  const refreshSaved = useCallback(
    () => listConversations().then(list => setSaved({ ...list,
      conversations: list.conversations.filter(c => (c.persona_id ?? null) === (persona?.id ?? null)),
    })).catch(() => {}), [persona?.id]);
  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  /** Write the conversation to disk.
   *
   *  Called after each reply rather than on a timer or at quit: a crash, a
   *  force-quit and a flat battery all skip anything scheduled for later, and
   *  those are exactly the moments this exists for.
   */
  const persist = useCallback(async (id: string, turns: ChatMessage[],
                                   continuity?: Continuity) => {
    if (!turns.length) return;
    try {
      await writeConversation(id, { messages: turns, model_path: activeModel?.path ?? null,
        compact_summary: continuity?.summary ?? compactSummary,
        compacted_through: continuity?.through ?? compactedThrough, persona: sessionPersona });
      refreshSaved();
    } catch {
      // Saving is not the user's job to supervise. A failure here must not
      // interrupt a conversation that is otherwise working.
    }
  }, [activeModel, compactSummary, compactedThrough, refreshSaved, sessionPersona]);

  const startNew = useCallback(() => {
    setSessionPersona(persona);
    generationEpoch.current += 1;
    chatAbort.current?.abort();
    compactAbort.current?.abort();
    setCompacting(false);
    setContextNotice('');
    chatAbort.current = null;
    printerSound.stop();
    setGenerating(false);
    setMessages([]);
    setCompactSummary('');
    setCompactedThrough(0);
    setContextUsage(null);
    setPreviews({});
    setConversationId(null);
    setAttached([]);
    setAttachedFiles([]);
    setInput('');
  }, [persona]);

  const openSaved = useCallback(async (id: string) => {
    generationEpoch.current += 1;
    chatAbort.current?.abort();
    compactAbort.current?.abort();
    setCompacting(false);
    setContextNotice('');
    chatAbort.current = null;
    printerSound.stop();
    setGenerating(false);
    try {
      const conversation = await readConversation(id);
      if ((conversation.persona?.id ?? null) !== (persona?.id ?? null)) return;
      setSessionPersona(conversation.persona ?? undefined);
      // Stored as the model wrote it, tags and all. Splitting on load rather
      // than on save keeps the file a faithful record of the reply, and means
      // a conversation saved before this existed opens correctly too.
      void loadDrawn(conversation.messages);
      setMessages(conversation.messages.map((m) => {
        if (m.role !== 'assistant' || m.reasoning) return m;
        const { thinking, answer } = splitThinking(m.content);
        return thinking ? { ...m, content: answer, reasoning: thinking } : m;
      }));
      setCompactSummary(conversation.compact_summary || '');
      setCompactedThrough(conversation.compacted_through || 0);
      setConversationId(conversation.id);
      setAttached([]);
      setAttachedFiles([]);
    } catch {
      // A conversation that will not decrypt is already reported in the list;
      // failing to open it must not blank the one on screen.
    }
  }, [loadDrawn, persona?.id]);

  useEffect(() => {
    const open = (event: Event) => { const id = (event as CustomEvent<string>).detail;
      if (typeof id === 'string') void openSaved(id); };
    window.addEventListener('uncloud.open-conversation', open);
    return () => window.removeEventListener('uncloud.open-conversation', open);
  }, [openSaved]);
  useEffect(() => () => {
    generationEpoch.current += 1;
    chatAbort.current?.abort();
    compactAbort.current?.abort();
    printerSound.stop();
  }, []);

  const removeSaved = useCallback(async (id: string) => {
    await deleteConversation(id).catch(() => {});
    if (id === conversationId) startNew();
    refreshSaved();
  }, [conversationId, startNew, refreshSaved]);

  /** Whether the loaded model can receive a picture at all. */
  useEffect(() => {
    let cancelled = false;
    engineStatus()
      .then((st) => { if (!cancelled) setVisionOk(!!st.supports_vision); })
      .catch(() => { if (!cancelled) setVisionOk(false); });
    return () => { cancelled = true; };
  }, [activeModel]);

  const attachDocuments = useCallback(() => {
    const picker = document.createElement('input');
    picker.type = 'file';
    // Let the local reader validate files. WebView file-type filters can hide
    // readable documents/source files, particularly unregistered extensions.
    picker.multiple = true;
    picker.onchange = async () => {
      setAttachingFile(true);
      setLastError(null);
      const errors: string[] = [];
      try {
        for (const file of Array.from(picker.files ?? [])) {
          try {
            if (file.size > 10 * 1024 * 1024) throw new Error('That file is larger than 10 MB.');
            if (file.type.startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp|tiff?|heic)$/i.test(file.name)) {
              if (!visionOk) {
                throw new Error('This model cannot see images. Load a vision model from Models, '
                  + 'then attach the screenshot again.');
              }
              if (!/\.(png|jpe?g|webp)$/i.test(file.name)) {
                throw new Error('Use PNG, JPEG or WebP for images.');
              }
              const url = await new Promise<string>((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result || ''));
                reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
                reader.readAsDataURL(file);
              });
              setAttached((current) => [...current, url]);
              continue;
            }
            const attachment = await uploadChatAttachment(file);
            setAttachedFiles((current) => [...current, attachment]);
          } catch (error) {
            errors.push(`${file.name}: ${String(error).replace(/^Error:\s*/, '')}`);
          }
        }
      } finally {
        if (errors.length) setLastError(errors.join('\n'));
        setAttachingFile(false);
      }
    };
    picker.click();
  }, [visionOk]);

  async function send(text: string, readAloud: boolean,
                      say?: (sentence: string) => void) {
    // A picture on its own is a perfectly good question — "what is this?" is
    // implied — so an empty box with an attachment still sends.
    if ((!text.trim() && !attached.length && !attachedFiles.length)
        || !activeModel || generating || compacting || loadingModel || attachingFile) return;
    // Audio contexts may only be unlocked by a user gesture. Do that now,
    // before loading a model, but do not actually make noise until the first
    // visible reply text arrives.
    printerSound.prepare();
    const sendingConversationId = conversationId ?? newConversationId();
    if (!conversationId) setConversationId(sendingConversationId);
    const images = attached;
    const files = attachedFiles;
    const next = [...messages, {
      role: 'user', content: text.trim(), ...(images.length ? { images } : {}),
      ...(files.length ? { files } : {}),
    } as ChatMessage];
    setMessages(next);
    setAttached([]);
    setAttachedFiles([]);
    setInput('');
    setConsulted([]);
    setLooking([]);
    setGenerating(true);
    setMessages((m) => [...m, { role: 'assistant', content: '' }]);
    const epoch = ++generationEpoch.current;
    let full = '';
    const renderedCharts: BarChartData[] = [];
    const controller = new AbortController();
    chatAbort.current = controller;
    try {
      const assistantIndex = next.length;
      //: The turns actually sent. It grows when the model asks to look
      //  something up, so its own request and the results are both in context
      //  for the answer that follows.
      let sent: ChatMessage[] = [
        ...next.slice(rawMode ? 0 : compactedThrough),
      ];
      let memory = compactSummary;
      let through = rawMode ? 0 : compactedThrough;
      let fittedReplyBudget: number | undefined;
      const lookups = new LookupSession();
      let nativeTurns: ChatMessage[] = [];
      let historyRounds = 0;
      let chartRounds = 0;
      const historyQueries = new Set<string>();
      const toolsEnabled = () => nativeWeb && lookups.phase !== 'final';
      const historyEnabled = () => nativeToolsAvailable && through > 0 && historyRounds < 3;
      const chartsEnabled = () => nativeToolsAvailable && renderedCharts.length === 0 && chartRounds < 2;
      const requestedLookup = web && !rawMode ? initialWebLookup(text) : null;
      const requestedPictures = pictures && !rawMode && wantsPictures(text);
      const turnInference = inference.values;
      const replyPrompt = () => systemPrompt({ pictures: requestedPictures, web, manner,
        spoken: readAloud, webPhase: web && !rawMode ? lookups.phase : undefined });
      const prepare = async (tail: ChatMessage[], allowOverflow = false) => {
        if (rawMode) return tail;
        const result = await prepareConversation([...next.slice(0, through), ...tail], {
          summary: memory, through, system: replyPrompt(), signal: controller.signal, allowOverflow,
          count: (turns, archived) => countChatContext(turns, turnInference, toolsEnabled(),
            nativeToolsAvailable && archived && historyRounds < 3, chartsEnabled()),
          compact: async (turns, previous) => {
            setCompacting(true);
            try {
              const result = await apiPost<{ summary: string }>('/api/context/compact', {
                messages: turns, memory: previous, inference: turnInference,
              }, controller.signal);
              return result.summary;
            } finally { if (epoch === generationEpoch.current) setCompacting(false); }
          },
        });
        if (epoch !== generationEpoch.current) throw new DOMException('Stopped', 'AbortError');
        if (result.summary !== memory || result.through !== through) {
          memory = result.summary; through = result.through;
          setCompactSummary(memory); setCompactedThrough(through);
          await persist(sendingConversationId, next, { summary: memory, through });
        }
        if (epoch !== generationEpoch.current || controller.signal.aborted) {
          throw new DOMException('Stopped', 'AbortError');
        }
        if (result.notice) setContextNotice(result.notice);
        setContextUsage(result.usage);
        if (result.usage.used != null && result.usage.limit) {
          fittedReplyBudget = Math.min(Number(turnInference.max_tokens ?? result.usage.reply_limit
            ?? result.usage.limit), Math.max(1, result.usage.limit - result.usage.used));
        }
        return result.tail;
      };
      const fitEvidence = async (evidence: string, assemble: (text: string) => ChatMessage[],
                                 assemblyThrough = through) => {
        const tail = (value: string) => assemble(value).slice(through - assemblyThrough);
        await prepare(tail(evidence), true);
        const fitted = await fitWebContext(evidence,
          value => contextMessages(tail(value), replyPrompt(), memory, 0, rawMode),
          turns => countChatContext(turns, turnInference, toolsEnabled(), historyEnabled(), chartsEnabled()),
          inference.values.max_tokens !== undefined ? Number(inference.values.max_tokens) : undefined);
        if (epoch !== generationEpoch.current || controller.signal.aborted) throw new Error('Reply stopped');
        setContextUsage(fitted.usage);
        fittedReplyBudget = fitted.replyBudget;
        return tail(fitted.evidence);
      };
      sent = await prepare(sent);
      // Models without verified native tool support still get lexical recall
      // from this conversation, measured before any excerpt enters the prompt.
      if (!rawMode && through > 0 && !nativeToolsAvailable) {
        const matches = searchHistory(next, through, text);
        if (matches.length) {
          const evidence = JSON.stringify({ conversation_history: matches });
          const beforeRecall = sent;
          sent = await fitEvidence(evidence, value => beforeRecall.map((message, index) =>
            index === beforeRecall.length - 1 ? { ...message,
              content: `${message.content}\n\n${value}` } : message));
        }
      }
      //: Hands-free only: the reply is cut into sentences as it is written so
      //  each can be spoken while the rest is still coming.
      const sentences = say ? new Sentences() : null;
      if (requestedLookup) {
        const lookup = requestedLookup;
        setLooking([describe(lookup)]);
        let evidence: string;
        try { evidence = lookup.kind === 'read' ? (await webRead(lookup.argument)).text
          : (await webSearch(lookup.argument)).results; }
        catch (e) {
          throw new Error(`Web lookup failed, so I could not verify this answer. ${e instanceof Error ? e.message : String(e)}`);
        } finally { setLooking([]); }
        if (epoch !== generationEpoch.current || controller.signal.aborted) return;
        setLooking([]);
        setConsulted([lookup.argument]);
        lookups.record([lookup]);
        // Keep the evidence beside the latest user request to suit local models
        // that require alternating user/assistant turns.
        const beforeSearch = sent;
        sent = await fitEvidence(evidence, value => beforeSearch.map((message, index) => index === beforeSearch.length - 1
          ? { ...message, content: `${message.content}\n\n${resultsTurn([{ lookup, text: value }])}` }
          : message));
        const retrieved = sent.at(-1)!.content.slice(beforeSearch.at(-1)!.content.length + 2);
        next[next.length - 1] = { ...next[next.length - 1], retrieved };
        setMessages(current => current.map((message, index) => index === next.length - 1
          ? { ...message, retrieved } : message));
      }


      for (;;) {
        full = '';
        let calls: ChatToolCall[] = [];
        for await (const chunk of streamChat(
          contextMessages(sent, replyPrompt(), memory, 0, rawMode),
          controller.signal,
          fittedReplyBudget,
          { path: activeModel.path, engine: activeModel.engine, adapter: activeAdapter,
            inference: { ...turnInference, ...(fittedReplyBudget ? { max_tokens: fittedReplyBudget } : {}) },
            conversationId: sendingConversationId, webTools: toolsEnabled(), historyTools: historyEnabled(), chartTools: chartsEnabled() },
        )) {
          if (epoch !== generationEpoch.current) return;
          if (chunk.kind === 'tool_calls') {
            calls = chunk.tool_calls ?? [];
            continue;
          }
          if (chunk.kind === 'text') {
            full += chunk.text;
            if (cleanReply(stripLookups(full), true).trim()) printerSound.writing();
          }
          // Hands-free: each finished sentence is spoken while the rest is
          // still being written, which is most of the wait removed.
          if (say && sentences && chunk.kind === 'text') {
            for (const sentence of sentences.push(chunk.text)) {
              const spoken = cleanReply(stripLookups(sentence), true).trim();
              if (spoken) say(spoken);
            }
          }
          setMessages((m) => {
            if (epoch !== generationEpoch.current) return m;
            const copy = [...m];
            const prev = copy[assistantIndex];
            if (!prev) return m;
            copy[assistantIndex] = chunk.kind === 'thinking'
              ? { ...prev, reasoning: (prev.reasoning ?? '') + chunk.text }
              : { ...prev, content: chartReply(full, renderedCharts) };
            return copy;
          });
        }
        // writing() stops itself after a short quiet period. That matters when
        // a fast local server delivers the whole answer in one frame: stopping
        // here muted the fade-in before a single audible sample was played.

        // With pictures off, a model that asks for one anyway is simply not
        // given one — the switch has to hold whatever the model does with the
        // prompt, or it is not a switch.
        // Both switches hold whatever the model wrote. A model told it is
        // offline will occasionally ask to search anyway, and the setting has
        // to win that argument rather than merely take part in it.
        // Only structured native calls can search/read. Text and thinking
        // cannot trigger a web request. Pictures retain their opt-in protocol.
        const chartCalls = calls.filter(call => call.function.name === 'render_bar_chart');
        const chartResults = new Map<string, string>();
        if (chartCalls.length) {
          if (!chartsEnabled() || chartCalls.length > 4) throw new Error('The chart tool limit was reached for this reply.');
          chartRounds++;
          for (const call of chartCalls) {
            const result = readBarChart(call.function.arguments);
            if (result.chart) {
              renderedCharts.push(result.chart);
              chartResults.set(call.id, '{"rendered":true}');
            } else chartResults.set(call.id, JSON.stringify({ error: result.error }));
          }
          if (chartRounds >= 2 && !renderedCharts.length) throw new Error('The model returned invalid chart data again after one correction attempt.');
          setMessages(current => current.map((message, index) => index === assistantIndex
            ? { ...message, content: chartReply(full, renderedCharts) } : message));
        }
        const recallCalls = calls.filter(call => call.function.name === 'conversation_search');
        const recallResults = new Map<string, string>();
        if (recallCalls.length) {
          if (!historyEnabled()) throw new Error('Conversation recall is unavailable or its per-reply limit was reached.');
          historyRounds++;
          for (const call of recallCalls) {
            const query = historyQuery(call);
            const key = query.trim().toLocaleLowerCase();
            const matches = historyQueries.has(key) ? [] : searchHistory(next, through, query);
            historyQueries.add(key);
            recallResults.set(call.id, JSON.stringify({ conversation_history: matches }));
          }
          setContextNotice('Earlier conversation searched locally.');
        }
        const webCalls = calls.filter(call => !['conversation_search', 'render_bar_chart'].includes(call.function.name));
        const requested = webCalls.length && nativeWeb
          ? webCalls.map(lookupForTool)
          : [];
        const pictureRequests = requestedPictures
          ? findLookups(full).filter(l => l.kind === 'pictures') : [];
        const plan = web && !rawMode
          ? lookups.nextRequests([...requested, ...pictureRequests])
          : { kind: 'done' as const, lookups: [] };
        if (plan.kind === 'done' && !recallCalls.length && !chartCalls.length) break;
        if (plan.kind === 'answer' && !calls.length) {
          setMessages(current => current.map((message, index) => index === assistantIndex
            ? { ...message, content: '', reasoning: '' } : message));
          continue;
        }
        const wanted = plan.lookups;

        // What is happening to their network connection, in plain words and
        // before it happens.
        setLooking(wanted.map(describe));
        const shown: WebImage[] = [];
        const fetched = await Promise.all(wanted.map(async (lookup) => {
          try {
            if (lookup.kind === 'pictures') {
              const { images } = await webImages(lookup.argument);
              shown.push(...images);
              // The model is told they were shown, not what is in them. It
              // cannot see them, and describing them to it as though it could
              // is how a model ends up confidently discussing a picture it has
              // no access to.
              return {
                lookup,
                text: JSON.stringify({ images: { displayed: images.length, visible_to_model: false } }),
                failed: false,
              };
            }
            const text = lookup.kind === 'search'
              ? (await webSearch(lookup.argument)).results
              : (await webRead(lookup.argument)).text;
            return { lookup, text, failed: false };
          } catch (e) {
            // A failed lookup is reported to the MODEL, not swallowed, so it
            // can say the search did not work rather than inventing an answer.
            return { lookup, failed: true, text: JSON.stringify({ error: {
              code: 'lookup_failed', message: e instanceof Error ? e.message : String(e),
            } }) };
          }
        }));
        setLooking([]);
        if (epoch !== generationEpoch.current) return;
        if (fetched.length && fetched.every(part => part.failed)) {
          setContextNotice('Search providers returned no usable sources. This reply has no verified web evidence yet.');
          if (!calls.length) throw new Error('Web lookup failed. Search providers returned no usable sources.');
        } else if (fetched.length) setContextNotice('Web sources retrieved.');
        if (wanted.length) lookups.record(wanted);
        setConsulted((c) => [...c, ...wanted.map(l => l.argument)]);
        if (shown.length) {
          setMessages((m) => {
            if (epoch !== generationEpoch.current) return m;
            const copy = [...m];
            const prev = copy[assistantIndex];
            if (!prev) return m;
            copy[assistantIndex] = { ...prev, found: [...(prev.found ?? []), ...shown] };
            return copy;
          });
        }

        // The request stays in the transcript the model sees — without it the
        // results arrive as an answer to nothing.
        if (calls.length) {
          const lookupThrough = through;
          const beforeLookup: ChatMessage[] = [...sent,
            { role: 'assistant', content: full, tool_calls: calls }];
          const responses: ChatMessage[] = calls.map(call => {
            const lookup = ['conversation_search', 'render_bar_chart'].includes(call.function.name) ? null : lookupForTool(call);
            const part = lookup && fetched.find(p => lookupKey(p.lookup) === lookupKey(lookup));
            return { role: 'tool', tool_call_id: call.id,
              content: chartResults.get(call.id) ?? recallResults.get(call.id) ?? (part ? part.text : null)
                ?? '{"results":[],"status":"lookup_limit"}' };
          });
          // Fit actual tool outputs with all call IDs and tool definitions
          // present. Keep the user's conversation and every supporting URL.
          await prepare([...beforeLookup, ...responses], true);
          const retained = beforeLookup.slice(through - lookupThrough);
          const assemble = (values: string[]) => [...retained,
            ...responses.map((response, index) => ({ ...response, content: values[index] }))];
          const fitted = await fitToolContext(responses.map(response => response.content),
            values => contextMessages(assemble(values), replyPrompt(), memory, 0, rawMode),
            turns => countChatContext(turns, turnInference, toolsEnabled(), historyEnabled(), chartsEnabled()),
            turnInference.max_tokens !== undefined ? Number(turnInference.max_tokens) : undefined);
          controller.signal.throwIfAborted();
          if (epoch !== generationEpoch.current) return;
          fittedReplyBudget = fitted.replyBudget;
          setContextUsage(fitted.usage);
          sent = assemble(fitted.evidence);
          nativeTurns = [...nativeTurns, beforeLookup.at(-1)!, ...sent.slice(retained.length)];
          next[next.length - 1] = { ...next[next.length - 1], tool_turns: nativeTurns };
          setMessages(current => current.map((message, index) => index === next.length - 1
            ? { ...message, tool_turns: nativeTurns }
            : index === assistantIndex ? { ...message, content: chartReply('', renderedCharts), reasoning: '' } : message));
          // Rendering is the requested result. No second model pass is needed
          // to describe or redraw an artifact that is already on screen.
          if (chartCalls.length && chartCalls.length === calls.length && renderedCharts.length) break;
          continue;
        }
        const beforeLookup = [
          ...sent,
          { role: 'assistant', content: full },
        ] as ChatMessage[];
        sent = await fitEvidence(resultsTurn(fetched), value => [
          ...beforeLookup, { role: 'user', content: value },
        ]);
        const retrieved = [next.at(-1)?.retrieved, sent.at(-1)!.content].filter(Boolean).join('\n\n');
        next[next.length - 1] = { ...next[next.length - 1], retrieved };
        setMessages((m) => {
          if (epoch !== generationEpoch.current) return m;
          const copy = [...m];
          const prev = copy[assistantIndex];
          if (!prev) return m;
          copy[assistantIndex] = { ...prev, content: '', reasoning: '' };
          copy[next.length - 1] = { ...copy[next.length - 1], retrieved };
          return copy;
        });
      }

      // The markers were an instruction to the application, not part of the
      // answer. Left in, the user reads the plumbing.
      const rawReply = full;
      full = rawMode ? full : cleanReply(stripLookups(full));
      full = chartReply(full, renderedCharts);
      if (!full.trim()) throw new Error('The model finished without an answer. Its thinking is available above; no lookup was executed from thinking text.');
      setMessages((m) => {
        if (epoch !== generationEpoch.current) return m;
        const copy = [...m];
        const prev = copy[assistantIndex];
        if (!prev) return m;
        copy[assistantIndex] = { ...prev, content: full };
        return copy;
      });
      // Saved now the exchange is complete. The id is minted on the first
      // save rather than when the view opens, so opening Chat and changing
      // your mind does not leave an empty conversation in the list.
      const id = sendingConversationId;
      if (epoch !== generationEpoch.current) return;
      if (!conversationId) setConversationId(id);
      void persist(id, [...next, { role: 'assistant', content: full } as ChatMessage], { summary: memory, through });
      // Fire and forget: the reply is already readable, and a render may take
      // minutes. Pass the freshly minted id explicitly; state has not rerendered
      // yet on the first turn, and closing the phone must not orphan the file.
      if (requestedPictures) void renderPreviews(assistantIndex, rawReply, epoch, id);

      // The tail: an answer that ends without punctuation, or a last clause
      // too short to have been spoken on its own.
      if (say && sentences) {
        const tail = cleanReply(stripLookups(sentences.rest())).trim();
        if (tail) say(tail);
      }
      if (readAloud && !say && full.trim()) {
        setSpeaking(true);
        try {
          const url = await speakReply(full.trim(), voice);
          if (epoch !== generationEpoch.current) return;
          if (audioRef.current) {
            audioRef.current.src = url;
            await audioRef.current.play();
            await new Promise<void>((resolve) => {
              const done = () => resolve();
              audioRef.current!.onended = done;
              audioRef.current!.onerror = done;
            });
          }
        } finally {
          setSpeaking(false);
        }
      }
    } catch (e) {
      printerSound.stop();
      if (epoch !== generationEpoch.current) return;
      if (e instanceof DOMException && e.name === 'AbortError') {
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last?.role === 'assistant' && !last.content.trim()) {
            copy[copy.length - 1] = { ...last, content: 'Stopped.' };
          }
          return copy;
        });
      } else {
        // A rejected request must not consume the documents before the model
        // has answered. Failed turns are deliberately excluded from context;
        // return their attachments to the composer for an explicit retry.
        if (!full.trim() && (files.length || images.length)) {
          setAttachedFiles(current => [...files.filter(file => !current.includes(file)), ...current]);
          setAttached(current => [...new Set([...images, ...current])]);
          setInput(current => current || text);
        }
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last?.role === 'assistant') {
            copy[copy.length - 1] = { ...last,
              content: rawMode ? last.content : cleanReply(stripLookups(last.content)),
              error: e instanceof Error ? e.message : String(e) };
          }
          return copy;
        });
      }
    } finally {
      if (epoch === generationEpoch.current) {
        chatAbort.current = null;
        setGenerating(false);
      }
    }
  }

  function stopGenerating() {
    generationEpoch.current += 1;
    chatAbort.current?.abort();
    compactAbort.current?.abort();
    setCompacting(false);
    chatAbort.current = null;
    printerSound.stop();
    setGenerating(false);
  }

  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    chunks.current = [];
    rec.ondataavailable = (e) => chunks.current.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      if (!sttModel) return;
      setTranscribing(true);
      try {
        const blob = new Blob(chunks.current, { type: 'audio/webm' });
        const text = await transcribeAudio(sttModel.path, blob);
        if (text.trim()) send(text, true);
      } finally {
        setTranscribing(false);
      }
    };
    rec.start();
    mediaRecorder.current = rec;
    setRecording(true);
  }

  function stopRecording() {
    mediaRecorder.current?.stop();
    setRecording(false);
  }

  useEffect(() => {
    if (!visible || !activeModel || generating || compacting) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      const currentText = input.trim() || [...messages].reverse().find(m => m.role === 'user')?.content || '';
      const turns = contextMessages([
        ...messages,
        ...(input.trim() ? [{ role: 'user' as const, content: input.trim() }] : []),
      ], systemPrompt({ pictures: pictures && wantsPictures(currentText), web, manner,
        webPhase: web && !rawMode ? 'request' : undefined }), compactSummary, compactedThrough, rawMode);
      void countChatContext(turns, inference.values, nativeWeb, nativeToolsAvailable && compactedThrough > 0, nativeToolsAvailable).then((usage) => {
        if (!cancelled) setContextUsage(usage);
      }).catch(() => { if (!cancelled) setContextUsage(null); });
    }, 550);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [activeModel, messages, input, compactSummary, compactedThrough, generating,
      compacting, pictures, web, nativeWeb, nativeToolsAvailable, manner, rawMode, inference.values, inference.info, systemPrompt, visible]);

  async function compactConversation() {
    if (!activeModel || generating || compacting || !messages.length) return;
    const through = messages.length > 4 ? messages.length - 2 : messages.length;
    if (through <= compactedThrough) return;
    const epoch = generationEpoch.current;
    const controller = new AbortController();
    compactAbort.current = controller;
    setCompacting(true);
    try {
      const result = await apiPost<{ summary: string }>('/api/context/compact', {
        messages: messages.slice(compactedThrough, through), memory: compactSummary,
        inference: inference.values,
      }, controller.signal);
      if (epoch !== generationEpoch.current || controller.signal.aborted) return;
      const summary = result.summary.trim();
      if (!summary) throw new Error('The model returned an empty summary.');
      const system = systemPrompt({ pictures: false, web, manner,
        webPhase: web && !rawMode ? 'request' : undefined });
      const [before, after] = await Promise.all([
        countChatContext(contextMessages(messages, system, compactSummary, compactedThrough), inference.values, nativeWeb, nativeToolsAvailable && compactedThrough > 0, nativeToolsAvailable),
        countChatContext(contextMessages(messages, system, summary, through), inference.values, nativeWeb, nativeToolsAvailable, nativeToolsAvailable),
      ]);
      if (before.used == null || after.used == null) {
        throw new Error('Could not verify the compacted context size. Your original conversation is preserved.');
      }
      if (after.used >= before.used) {
        throw new Error('The summary did not reduce context. Your original conversation is preserved.');
      }
      if (epoch !== generationEpoch.current || controller.signal.aborted) return;
      if (conversationId) {
        await writeConversation(conversationId, { messages, model_path: activeModel.path,
          compact_summary: summary, compacted_through: through, persona: sessionPersona });
        refreshSaved();
      }
      if (epoch !== generationEpoch.current || controller.signal.aborted) return;
      setCompactSummary(summary);
      setCompactedThrough(through);
      setContextNotice('Earlier messages compacted. Originals remain available for recall.');
    } catch (error) {
      if (!controller.signal.aborted && epoch === generationEpoch.current) {
        setContextNotice(`Could not compact: ${error instanceof Error ? error.message : String(error)}. Original history is preserved.`);
      }
    } finally {
      if (epoch === generationEpoch.current) setCompacting(false);
      if (compactAbort.current === controller) compactAbort.current = null;
    }
  }

  const empty = messages.length === 0;

  const composer = (
    <div className="composer-inner">
      {(loadingModel || generating || compacting) && <div role="status" className="chat-generation-status">
        <ActivityOrb size={20} state={loadingModel ? 'connecting' : compacting ? 'shaping' : 'solving'}
          label={loadingModel ? 'Loading model' : compacting ? 'Compacting context' : 'Model responding'} />
        <span>{loadingModel ? 'Model warm-up…' : compacting ? 'Compacting conversation memory…' : messages.at(-1)?.content ? 'Response in flight…' : 'Awaiting model response…'}</span>
      </div>}
      <div className="composer-card chat-composer">
        {/* What is going with the next message. Shown before sending, and
            removable: attaching the wrong screenshot is easy and noticing
            after the model has answered is too late. */}
        {(attached.length > 0 || attachedFiles.length > 0) && (
          <div className="composer-attachments flex flex-wrap gap-2 px-1 pb-2">
            {attached.map((url, i) => (
              <div key={i} className="relative">
                <img src={url} alt="" className="h-20 w-20 object-cover rounded-lg
                                                 border border-[var(--border)]" />
                <button
                  className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[var(--bg-inset)]
                             border border-[var(--border)] flex items-center justify-center"
                  title="Remove"
                  onClick={() => setAttached((a) => a.filter((_, k) => k !== i))}
                >
                  <X size={9} />
                </button>
              </div>
            ))}
            {attachedFiles.map((file, i) => (
              <div key={`${file.name}-${i}`} className="relative flex items-center gap-2 h-14 max-w-52
                                                    px-3 pr-6 rounded-lg border border-[var(--border)]
                                                    bg-[var(--bg-inset)] text-xs">
                <FileText size={15} className="shrink-0 text-[var(--text-faint)]" />
                <span className="truncate" title={file.clipped ? `${file.name} · Text excerpt (reading limit reached)` : file.name}>
                  {file.name}{file.clipped && <span className="faint"> · Excerpt</span>}
                </span>
                <button
                  className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[var(--bg-inset)]
                             border border-[var(--border)] flex items-center justify-center"
                  title="Remove"
                  onClick={() => setAttachedFiles((items) => items.filter((_, k) => k !== i))}
                >
                  <X size={9} />
                </button>
              </div>
            ))}
          </div>
        )}
        <AutoGrowTextarea
          aria-label="Message"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(input, autoSpeak);
            }
          }}
          placeholder={activeModel ? 'Ask anything' : 'Ask anything'}
          // Deliberately NOT disabled. Writing a question while a model is
          // still loading is normal; a field that refuses input reads as a
          // broken application rather than as a precondition. Only sending is
          // gated.
          rows={1}
          className="composer-input"
        />

        <div className="composer-actions">
          <button onClick={attachDocuments} disabled={!activeModel || loadingModel || attachingFile}
            title={visionOk ? 'Attach PDF, documents, text or images (10 MB each)' : 'Attach PDF, documents or text (10 MB each). Images need a vision model.'}
            aria-label={visionOk ? 'Attach files or images' : 'Attach files'} className="pill pill-icon composer-attach">
            {attachingFile ? <ActivityOrb state="working" size={20} label="Reading file…" /> : <Paperclip size={17} />}
          </button>
          {sttModel && (
            <button
              onClick={recording ? stopRecording : startRecording}
              disabled={!activeModel || transcribing}
              title={recording ? 'Stop recording' : `Dictate with ${sttModel.name}`}
              aria-label={recording ? 'Stop recording' : 'Dictate'}
              className={recording ? 'pill pill-icon pill-on' : 'pill pill-icon'}
              style={recording ? { color: 'var(--danger)' } : undefined}
            >
              {transcribing ? <ActivityOrb state="working" size={20} label="Working…" />
                : recording ? <Square size={11} fill="currentColor" />
                : <Mic size={15} />}
            </button>
          )}

          <details className="relative" onToggle={(e) => {
            const menu = e.currentTarget.querySelector<HTMLElement>('.composer-menu');
            if (menu) menu.style.maxHeight = `${Math.max(120, Math.min(520, e.currentTarget.getBoundingClientRect().top - 20))}px`;
            if (e.currentTarget.open) getPermissions().then((p) => setNetworkDenied(p.policy.network === 'deny')).catch(() => undefined);
          }}>
            <summary className="pill pill-icon list-none cursor-pointer" aria-label="Chat settings" title="Chat settings">
              <Settings2 size={15} />
            </summary>
            <div className="absolute bottom-full mb-2 left-0 z-40 card p-3 flex flex-col gap-2 composer-menu"
                 onKeyDown={(e) => { if (e.key === 'Escape') { e.currentTarget.closest('details')?.removeAttribute('open'); } }}>
              <span className="text-xs text-[var(--text-dim)]">Chat settings</span>
              {rawMode && <span className="text-xs">Direct-model diagnostic mode</span>}
              {activeModel && ['gguf', 'mlx', 'mlx-vlm'].includes(activeModel.engine) && <div className="text-xs flex flex-col gap-1">
                <label htmlFor="context-length">Model context window · applies when reloaded</label>
                <input id="context-length" className="input" type="number" min="256" step="1"
                  max={loadedContext.context_profile?.native_limit ?? undefined}
                  placeholder={`Auto · ${contextUsage?.limit ?? 'model and memory'}`} value={contextLength}
                  onChange={e => setContextLength(e.target.value)} />
                <span className="faint">Larger windows use more memory. Cannot exceed the model’s supported limit.</span>
                <span role="status" className="faint">
                  Loaded: {(loadedContext.context_limit ?? contextUsage?.limit)?.toLocaleString() ?? '—'} tokens
                  {loadedContext.context_profile?.native_limit
                    ? ` · Model maximum: ${loadedContext.context_profile.native_limit.toLocaleString()}` : ''}
                </span>
                <button className="pill" disabled={generating || loadingModel}
                  onClick={async () => {
                    setLoadingModel(true);
                    try {
                      const value = contextLength.trim() ? Number(contextLength) : undefined;
                      const maximum = loadedContext.context_profile?.native_limit;
                      if (value !== undefined && (!Number.isInteger(value) || value < 256
                        || (maximum != null && value > maximum))) {
                        throw new Error(`Choose a whole number from 256 to ${maximum?.toLocaleString() ?? 'the model maximum'}, or leave blank for Auto.`);
                      }
                      const status = await startEngine(
                        activeModel.path, activeModel.engine, activeAdapter, value, true);
                      setLoadedContext(status);
                      const windows = { ...contextWindows };
                      if (value === undefined) delete windows[activeModel.path];
                      else windows[activeModel.path] = value;
                      setContextWindows(windows);
                      localStorage.setItem('uncloud.chat.contextWindows', JSON.stringify(windows));
                      setNetworkError('');
                      await inference.refresh();
                      setContextUsage(await countChatContext(contextMessages(messages, systemPrompt({ pictures: false, web: false, manner }), compactSummary, compactedThrough, rawMode), inference.values, nativeWeb, nativeToolsAvailable && compactedThrough > 0, nativeToolsAvailable));
                    } catch (error) { setNetworkError(error instanceof Error ? error.message : String(error)); }
                    finally { setLoadingModel(false); }
                  }}>Apply context window</button>
              </div>}
              {activeModel && <InferenceControls compact info={inference.info} values={inference.values}
                onChange={inference.setValues} onRefresh={inference.refresh} conversationId={conversationId} />}
              {networkDenied && <div className="text-xs max-w-64">
                <p>Internet access is set to Never, even when Web is on.</p>
                <button className="pill mt-2" onClick={async () => {
                  try { const p = await setPermission('network', 'ask_category'); setNetworkDenied(p.policy.network === 'deny'); }
                  catch { setNetworkError('Could not change permission. Try again in Settings.'); }
                }}>Enable internet — ask once per session</button>
              </div>}
              {networkError && <p role="alert" className="text-xs">{networkError}</p>}
          {/* The only control here that governs the network. Labelled plainly,
              because "local-first" is the promise this application makes and
              an exception to it should be visible rather than discovered. */}
          <button
            onClick={() => setWeb((v) => !v)}
            title={web
              ? nativeWeb ? 'Web: native search and read tools available. Internet permission still applies.'
                : 'Native web tools are not available for this model/backend. You can still ask to read a supplied page URL.'
              : 'Web lookups: off — Chat will not search or read websites.'}
            className={web ? 'pill pill-on' : 'pill'}
          >
            {web ? <Globe size={15} /> : <GlobeLock size={15} />}
            <span>Web</span>
          </button>

          {/* Whether replies may include pictures. Beside Speak because it is
              the same kind of setting: how the next answer arrives, not what
              is in it. */}
          <button
            onClick={() => setPictures((v) => !v)}
            title={pictures
              ? 'Pictures in replies: on — the model may add images'
              : 'Pictures in replies: off'}
            className={pictures ? 'pill pill-on' : 'pill'}
          >
            {pictures ? <ImageIcon size={15} /> : <ImageOff size={15} />}
            <span>Pictures</span>
          </button>

          {/* Speaking replies is a property of the next message, so it belongs
              beside the field rather than up in the window chrome. */}
          <button
            onClick={() => setAutoSpeak((v) => !v)}
            title={autoSpeak ? 'Speak replies: on' : 'Speak replies: off'}
            className={autoSpeak ? 'pill pill-on' : 'pill'}
          >
            {speaking ? <ActivityOrb state="working" size={20} label="Working…" />
              : autoSpeak ? <Volume2 size={15} /> : <VolumeX size={15} />}
            <span>Speak</span>
          </button>

          {/* Hand the conversation to Chisel. Only once there is something to
              hand over, and never while the model is still writing — the last
              message is what becomes the goal, and half of it is not a goal. */}
          {messages.some((m) => m.role === 'user') && (
            <button
              onClick={() => sendToChisel(fromConversation(messages, activeModel))}
              disabled={generating}
              title="Continue this in Chisel, carrying the conversation"
              className="pill"
            >
              <Hammer size={15} />
              <span>Chisel</span>
            </button>
          )}

              <div className="border-t border-[var(--border)] pt-3 mt-1 flex flex-col gap-3">
              <label className="field">
                <span className="label" style={{ fontSize: 11 }}>Voice</span>
                <ReplyVoice className="input" value={voice} onChange={setVoice} />
              </label>
              <label className="field">
                <span className="label" style={{ fontSize: 11 }}>Spoken manner</span>
                <select className="input" value={manner}
                        onChange={(e) => setManner(e.target.value)}>
                  {MANNERS.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </label>
              <p className="faint" style={{ fontSize: 10, lineHeight: 1.5 }}>
                Applies only when a reply is read aloud. Typed chat uses no voice formatting.
                Voices you save in
                Voice → Text to voice appear here too.
              </p>
              </div>
            </div>
          </details>

          {/* Hands-free. The state is written out rather than left to a colour,
              because "is it listening to me right now" is the one question a
              voice interface must never leave ambiguous. */}
          {talk.ready && (
            <button
              onClick={toggleConversation}
              disabled={!activeModel}
              title={talk.active
                ? 'Stop the conversation'
                : talk.native
                  ? 'Talk instead of typing — this Mac transcribes as you speak'
                  : 'Talk instead of typing — it listens, answers aloud, and listens again'}
              className={talk.active ? 'pill pill-on' : 'pill pill-icon'}
              aria-label={talk.active ? 'Stop voice conversation' : 'Start voice conversation'}
              style={talk.active ? { color: 'var(--accent)' } : undefined}
            >
              {talk.active ? <AudioLines size={15} className="animate-pulse" />
                : <MessagesSquare size={15} />}
              <span className={!talk.active ? 'sr-only' : undefined}>
                {!talk.active ? 'Converse'
                  : talk.state === 'hearing' ? 'Listening…'
                  : talk.state === 'thinking' ? 'Thinking…'
                  : talk.state === 'speaking' ? 'Speaking…'
                  : 'Your turn'}
              </span>
            </button>
          )}

          <div className="composer-spacer" />
        <div ref={pickerRef} style={{ position: 'relative' }}>
          <button className="pill composer-model" title={activeModel ? `${activeModel.name}${activeAdapter ? ` · ${activeAdapter.split('/').pop()}` : ''}` : 'Choose a model'} aria-label="Choose a model" onClick={() => setPickerOpen((v) => !v)}
                  aria-haspopup="listbox" aria-expanded={pickerOpen}>
            {loadingModel ? (
              <><ActivityOrb state="connecting" label="Model warm-up…" /><span>Model warm-up…</span></>
            ) : activeModel ? (
              <>
                <span style={{
                  width: 6, height: 6, borderRadius: 999,
                  background: 'var(--success)', flex: 'none',
                }} />
                <span>{activeModel.name}{activeAdapter ? ` · ${activeAdapter.split('/').pop()}` : ''}</span>
              </>
            ) : (
              <span style={{ color: 'var(--text-3)' }}>Select model</span>
            )}
            <ChevronDown size={15} style={{ flex: 'none', color: 'var(--text-3)' }} />
          </button>

          {pickerOpen && (
            <div
              className="card no-drag chassis-scroll composer-model-menu"
              role="listbox"
              style={{
                position: 'absolute', bottom: 44, right: 0, zIndex: 50,
                width: 340, maxWidth: "calc(100vw - 32px)", maxHeight: Math.max(120, Math.min(320, (pickerRef.current?.getBoundingClientRect().top ?? window.innerHeight) - 20)), padding: 6,
                boxShadow: 'var(--shadow-lg)',
              }}
            >
              {models.length === 0 && (
                <div style={{
                  fontSize: 'var(--text-xs)', color: 'var(--text-3)',
                  padding: '16px 12px', textAlign: 'center',
                }}>
                  No text models yet. Download one from the Models tab, or add one you already have.
                </div>
              )}
              {models.map((m) => <div key={m.id}>
                <button onClick={() => selectModel(m)} role="option"
                        aria-selected={activeModel?.id === m.id && !activeAdapter} className="menu-row">
                  <span>{m.name}</span>
                  <span className="font-mono" style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', flex: 'none' }}>{m.engine}</span>
                </button>
                {m.engine === 'mlx' && adapters.filter((a) => a.ready && a.base_model === m.path).map((adapter) =>
                  <button key={adapter.path} onClick={() => selectModel(m, adapter)} role="option"
                          aria-selected={activeModel?.path === m.path && activeAdapter === adapter.path}
                          className="menu-row" style={{ paddingLeft: 24 }}
                          title={`Use ${m.name} with the trained adapter ${adapter.adapter}`}>
                    <span>↳ {adapter.adapter}</span><span style={{ fontSize: 10, color: 'var(--text-3)' }}>adapter</span>
                  </button>)}
              </div>)}
              {/* Pinned: the list scrolls, and an option below the fold is one nobody finds. */}
              <div style={{ borderTop: '1px solid var(--border-soft)', marginTop: 4, paddingTop: 4,
                            position: 'sticky', bottom: -6, background: 'inherit' }}>
                <AddFromDisk onOpen={() => setPickerOpen(false)} />
              </div>
            </div>
          )}
        </div>


          <button
            onClick={generating || compacting ? stopGenerating : () => send(input, autoSpeak)}
            disabled={!activeModel || loadingModel || (!generating && !compacting && (attachingFile
              || (!input.trim() && !attached.length && !attachedFiles.length)))}
            title={generating || compacting ? 'Stop response' : 'Send'}
            aria-label={generating || compacting ? 'Stop response' : 'Send'}
            className="composer-send"
          >
            {generating || compacting ? <Square size={12} fill="currentColor" /> : <ArrowUp size={17} />}
          </button>
        </div>
      </div>
      {activeModel && (contextUsage?.limit || compactSummary) && (
        <div className="chat-context-footer">
          {compactSummary && <details className="chat-context-memory">
            <summary>Compacted memory</summary>
            <div>{compactSummary}</div>
          </details>}
          {contextUsage?.limit && <details className="chat-context-memory">
            <summary aria-label="Context token details" role="status">
            {contextUsage.used == null ? (!messages.length && !input.trim()
              ? `${contextUsage.limit.toLocaleString()} context capacity` : 'Context count unavailable') :
              `${contextUsage.used.toLocaleString()} / ${contextUsage.limit.toLocaleString()} context tokens`}
            </summary>
            <div>Working context, counted with the loaded model’s native tokenizer and template.
              Includes retained messages, tool definitions and results, file text, and compacted memory.
              This is not a lifetime usage counter. Earlier archived messages remain saved for recall.
              <p className="mt-2">Loaded window: {contextUsage.limit.toLocaleString()} tokens.
                {loadedContext.context_profile?.native_limit ? ` Model maximum: ${loadedContext.context_profile.native_limit.toLocaleString()}.` : ''}
                {' '}Replies also need space inside this window.</p>
            </div>
          </details>}
          {!rawMode && compactAvailable(contextUsage?.used ?? null, contextUsage?.limit ?? null) &&
            <button onClick={() => void compactConversation()} disabled={compacting || generating}
                    title="Preserve important earlier context in an inspectable summary">
              {compacting ? 'Compacting…' : 'Compact'}
            </button>}
        </div>
      )}
      {contextNotice && <p role="status" className="px-3 pt-1 text-xs text-[var(--text-faint)]">{contextNotice}</p>}
    </div>
  );

  return (
    <div className="h-full flex flex-col relative">
      {/* Conversation navigation stays in the window chrome. */}
      <TitleBarPortal>
        <span className="text-sm text-[var(--text-dim)] px-2">{persona ? `Personas · ${persona.name}` : 'Chat'}</span>
        <span className="flex-1" />

        {/* Starting again, and going back to something. Both belong in the
            window chrome: they are about WHICH conversation, not about the
            one on screen. */}
        <button className="tb-btn" onClick={startNew} title="New conversation"
                aria-label="New conversation">
          <Plus size={15} />
        </button>
        <button className="tb-btn" onClick={() => setDrawerOpen(true)}
                title="Saved conversations" aria-label="Saved conversations">
          <PanelRight size={15} />
        </button>
        <button className="tb-btn" onClick={() => {
          setNotesOpen(true);
          void listNotes().then(setNotes).catch(() => {});
        }} title="Saved notes" aria-label="Saved notes">
          <NotebookPen size={15} />
        </button>
      </TitleBarPortal>

      {empty ? (
        /* Nothing to read yet, so the composer IS the page. */
        <div className="composer composer-centred">
          <div className="greeting">
            <Mark px={38} />
            <span>{persona ? persona.name : 'What are we making?'}</span>
          </div>
          {composer}
        </div>
      ) : (
        <>
          <div ref={scrollRef} className="flex-1 chassis-scroll chat-transcript">
            <div className="chat-message-list column flex flex-col pt-4 pb-12">
            {messages.map((m, i) => (
              <div key={`${conversationId ?? 'draft'}:${i}`} className={`chat-message ${m.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'}`}>
                {/* A reasoning model produces most of its tokens here before
                    answering. Hidden, it reads as a hung app; shown in full it
                    buries the answer. Collapsed, with a live hint while it is
                    still thinking. */}
                {m.role === 'assistant' && m.reasoning && (
                  <details className="mb-1.5 group">
                    <summary className="text-[11px] text-[var(--text-faint)] cursor-pointer select-none hover:text-[var(--text-dim)] transition">
                      {m.content ? 'Thought before answering' : generating && i === messages.length - 1 ? 'Thinking…' : 'Thinking finished'}
                      <span className="ml-1.5 opacity-60 group-open:hidden">
                        {m.reasoning.trim().split(/\s+/).length} words
                      </span>
                    </summary>
                    <div className="mt-1.5 text-[11px] text-[var(--text-faint)] whitespace-pre-wrap leading-relaxed border-l border-[var(--border-soft)] pl-3">
                      {m.reasoning.trimEnd()}
                    </div>
                  </details>
                )}
                {/* The user's own words go through verbatim: they typed
                    them, and reinterpreting an asterisk they meant literally
                    would be presumptuous. The model's answer is markdown,
                    because that is what it wrote whether or not anything was
                    rendering it. */}
                {m.role === 'user' ? (
                  <div className="bg-[var(--bg-raised)] border border-[var(--border)] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
                    {/* What was actually sent, kept with the turn. Without it
                        a reopened conversation reads as an answer to nothing. */}
                    {!!m.images?.length && (
                      <div className="flex flex-wrap gap-2 mb-2">
                        {m.images.map((url, k) => (
                          <img key={k} src={url} alt="" className="max-h-40 rounded-lg
                                                                   border border-[var(--border)]" />
                        ))}
                      </div>
                    )}
                    {!!m.files?.length && (
                      <div className="flex flex-wrap gap-1.5 mb-2">
                        {m.files.map((file, k) => (
                          <span key={`${file.name}-${k}`} className="inline-flex items-center gap-1.5
                                rounded-md border border-[var(--border)] px-2 py-1 text-[10px]
                                text-[var(--text-dim)] bg-[var(--bg-inset)]">
                            <FileText size={11} /> {file.name}{file.clipped ? ' · excerpt' : ''}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="whitespace-pre-wrap">
                      {m.content.replace(IMAGE_MARKER, '').trimEnd()}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-[var(--text)]">
                    {(() => {
                      const shown = cleanReply(m.content, generating && i === messages.length - 1);
                      if (shown) return <Markdown>{shown}</Markdown>;
                      // Still arriving.
                      if (i === messages.length - 1 && generating) {
                        return null;
                      }
                      // Nothing left after the markers were taken out: the
                      // model replied with an instruction and no words. The
                      // prompt tells it not to, but a prompt is a suggestion —
                      // and an empty bubble reads as the application losing the
                      // answer rather than the model never writing one.
                      // NOT IMAGE_MARKER.test(): it carries the /g flag, and
                      // test() on a global regex advances lastIndex, so the
                      // same string alternates true and false between renders.
                      if (m.drew?.length || m.found?.length
                          || m.content.includes('[[image:')) {
                        return (
                          <span className="text-[var(--text-faint)] italic">
                            (no words with this one — just the picture)
                          </span>
                        );
                      }
                      if (m.reasoning && !m.error) {
                        return (
                          <span className="text-[var(--text-faint)] italic">
                            (it thought, but wrote no answer — open the working above)
                          </span>
                        );
                      }
                      return null;
                    })()}
                  </div>
                )}
                {m.error && <p role="status" className="mt-2 px-1 text-xs text-[var(--text-dim)]">{m.error}</p>}
                {m.role === 'user' && m.content && (
                  <div className="chat-message-actions chat-message-actions-user flex items-center px-1
                                  text-[10px] text-[var(--text-faint)]">
                    <button className="pill h-7 px-2" title="Copy message" aria-label="Copy message"
                            onClick={() => void copyReply(i, m.content, true)}>
                      {copiedReply === i ? <Check size={11} /> : <Copy size={11} />}
                      <span>{copiedReply === i ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                )}
                {m.role === 'assistant' && cleanReply(m.content).trim()
                  && !(i === messages.length - 1 && generating) && (
                  <div className="chat-message-actions flex items-center gap-1 px-1 text-[10px]
                                  text-[var(--text-faint)]">
                    <button className="pill h-7 px-2" title="Copy reply"
                            onClick={() => void copyReply(i, m.content)}>
                      {copiedReply === i ? <Check size={11} /> : <Copy size={11} />}
                      <span>{copiedReply === i ? 'Copied' : 'Copy'}</span>
                    </button>
                    <button className="pill h-7 px-2" title="Save this reply as a note"
                            onClick={() => void noteReply(i, m.content)}>
                      {notedReply === i ? <Check size={11} /> : <NotebookPen size={11} />}
                      <span>{notedReply === i ? 'Saved' : 'Note'}</span>
                    </button>
                    <button className="pill h-7 px-2" title="Continue from here in Chisel"
                            onClick={() => sendToChisel(fromConversation(
                              messages.slice(0, i + 1), activeModel))}>
                      <Hammer size={11} /><span>Chisel</span>
                    </button>
                  </div>
                )}
                {/* Reaching the internet is the one thing this application
                    does that leaves the machine, so it is announced while it
                    happens rather than inferred afterwards. */}
                {m.role === 'assistant' && i === messages.length - 1
                  && looking.length > 0 && (
                  <div className="mt-2 flex flex-col gap-1">
                    {looking.map((what, k) => (
                      <div key={k} className="flex items-center gap-2 text-[11px]
                                              text-[var(--text-dim)] px-1">
                        <Globe size={12} className="animate-pulse" />
                        <span>{what}…</span>
                      </div>
                    ))}
                  </div>
                )}
                {m.role === 'assistant' && i === messages.length - 1
                  && !looking.length && consulted.length > 0 && (
                  <div className="mt-2 flex items-center gap-1.5 text-[11px]
                                  text-[var(--text-faint)] px-1 flex-wrap">
                    <Globe size={11} />
                    <span>Web lookup attempted: {consulted.join(' · ')}</span>
                  </div>
                )}

                {/* Pictures from the web. A strip rather than a grid: they
                    are examples beside an answer, not the answer. Each links
                    to where it came from, because a thumbnail with no
                    provenance is just an assertion. */}
                {!!m.found?.length && (
                  <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
                    {m.found.map((img, k) => (
                      <a key={k} href={img.source} target="_blank" rel="noopener noreferrer"
                         title={img.title || img.source}
                         className="shrink-0">
                        <img
                          src={img.thumbnail}
                          alt={img.title}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="h-28 w-28 object-cover rounded-lg border
                                     border-[var(--border)] hover:border-[var(--accent)]
                                     transition"
                        />
                      </a>
                    ))}
                  </div>
                )}

                {(previews[i] || []).map((p, k) => (
                  <div key={k} className="mt-2 max-w-[280px]">
                    {p.url ? (
                      <img
                        src={p.url}
                        alt={p.prompt}
                        className="w-full rounded-lg border border-[var(--border)]"
                      />
                    ) : p.error ? (
                      // Short, and in the user's terms. What was here was the
                      // raw loader exception — file paths and a missing
                      // component name — dropped into the middle of an answer
                      // about something else entirely. The detail belongs in a
                      // tooltip, not in the conversation.
                      // Short by default, and openable. The raw exception in
                      // the transcript was noise; the raw exception NOWHERE was
                      // worse — a failure nobody can diagnose, including the
                      // person who wrote it.
                      <details className="text-[11px] text-[var(--text-faint)] px-1">
                        <summary className="cursor-pointer select-none hover:text-[var(--text-dim)]">
                          The picture could not be made — why?
                        </summary>
                        <div className="mt-1 font-mono text-[10px] text-[var(--text-dim)]
                                        whitespace-pre-wrap break-words border-l
                                        border-[var(--border-soft)] pl-2">
                          {p.error}
                        </div>
                      </details>
                    ) : (
                      <div className="h-[140px] rounded-lg bg-[var(--bg-inset)] flex items-center justify-center">
                        <ActivityOrb state="shaping" size={32} label="Making the picture…" />
                      </div>
                    )}
                    {/* Only under an actual picture. It was captioning a
                        failure, explaining the settings of an image that was
                        never made. */}
                    {p.url && (
                      <div className="mt-1 px-1">
                        <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
                          Quick preview — 6 steps at 512px, for thinking with. Use the
                          Image tab for anything you intend to keep.
                        </p>
                        {/* It is already a file in the Outputs folder — this
                            is how to get to it, rather than a second copy. */}
                        {!!m.drew?.[k]?.path && (
                          <div className="mt-1 flex items-center gap-2">
                            <button
                              className="text-[10px] text-[var(--text-faint)] underline
                                         underline-offset-2 hover:text-[var(--text-dim)]"
                              onClick={() => revealOutput(m.drew![k].path).catch(() => {})}
                            >
                              Show in Finder
                            </button>
                            <a
                              className="text-[10px] text-[var(--text-faint)] underline
                                         underline-offset-2 hover:text-[var(--text-dim)]"
                              href={p.url}
                              download={`uncloud-${(m.drew![k].prompt || 'image')
                                .slice(0, 40).replace(/[^\w -]/g, '').trim()
                                .replace(/\s+/g, '-') || 'image'}.png`}
                            >
                              Save as…
                            </a>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}
            </div>
          </div>

          <div className="composer composer-docked">{composer}</div>
        </>
      )}

      {/* The conversation loop has nowhere else to report a refused
          microphone, and silence would read as the feature not working. */}
      {lastError && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-20 max-w-md
                        card px-3 py-2 text-[11px] text-[var(--text-dim)]
                        flex items-start gap-2">
          <span className="flex-1">{lastError}</span>
          <button className="tb-btn" onClick={() => setLastError(null)} title="Dismiss">
            <X size={12} />
          </button>
        </div>
      )}

      {notesOpen && (
        <div className="absolute inset-0 z-40 bg-black/35" onClick={() => setNotesOpen(false)}>
          <aside className="absolute right-0 top-0 bottom-0 w-[min(420px,92vw)]
                            bg-[var(--bg)] border-l border-[var(--border)] p-4
                            chassis-scroll" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-medium">Notes</h2>
                <p className="text-[10px] text-[var(--text-faint)] mt-0.5">
                  Saved on this device/session. They are never mixed across paired phones.
                </p>
              </div>
              <button className="tb-btn" onClick={() => setNotesOpen(false)} title="Close notes">
                <X size={14} />
              </button>
            </div>
            {notes.length === 0 ? (
              <p className="text-xs text-[var(--text-faint)]">No notes yet. Use Note below any reply.</p>
            ) : (
              <div className="flex flex-col gap-3">
                {notes.map((note) => (
                  <article key={note.key} className="card p-3">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-xs font-medium break-words">{note.key}</h3>
                      <button className="tb-btn shrink-0" title="Delete note" onClick={async () => {
                        await deleteNote(note.key);
                        setNotes((items) => items.filter((item) => item.key !== note.key));
                      }}><X size={12} /></button>
                    </div>
                    <div className="mt-2 text-xs text-[var(--text-dim)] whitespace-pre-wrap
                                    max-h-64 overflow-y-auto">{note.value}</div>
                  </article>
                ))}
              </div>
            )}
          </aside>
        </div>
      )}

      <Conversations
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        list={saved}
        activeId={conversationId}
        onOpen={openSaved}
        onNew={startNew}
        onDelete={removeSaved}
      />

      <audio ref={audioRef} className="hidden" />
    </div>
  );
}
