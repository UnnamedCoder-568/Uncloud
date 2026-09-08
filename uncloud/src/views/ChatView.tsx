import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ArrowUp, Square, Mic, Volume2, VolumeX, Loader2, Hammer, ImagePlus, PanelRight, Plus, X, Globe,
  Image as ImageIcon, ImageOff, GlobeLock, AudioLines, MessagesSquare,
  Settings2 } from 'lucide-react';
import { TitleBarPortal } from '../components/TitleBar';
import { Mark } from '../components/Wordmark';
import Markdown from '../components/Markdown';
import { fromConversation, sendToChisel } from '../lib/handoff';
import Conversations from '../components/Conversations';
import { splitThinking } from '../lib/thinking';
import { Conversation } from '../lib/converse';
import { MAX_ROUNDS, describe, findLookups, resultsTurn, stripLookups } from '../lib/lookup';
import { getLibrary, startEngine, engineStatus, streamChat, transcribeAudio, speakText, IMAGE_MARKER, chatSystemPrompt, quickImagePreview,
  listConversations, readConversation, writeConversation, deleteConversation,
  webSearch, webRead, webImages, VOICES, MANNERS,
  outputBlobUrl, revealOutput } from '../lib/sidecar';
import type { LocalModel, ChatMessage, ConversationList, WebImage } from '../lib/sidecar';

/** A conversation id: sixteen hex characters, which is what the engine accepts
 *  as a filename. `crypto.randomUUID` needs a secure context and is not
 *  guaranteed everywhere this window can run; `getRandomValues` is, and a
 *  silent failure here would be a conversation that never saves. */
function newConversationId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export default function ChatView() {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [activeModel, setActiveModel] = useState<LocalModel | null>(null);
  const [loadingModel, setLoadingModel] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  //: Which saved conversation this is. Made on the first send rather than on
  //  arrival, so opening Chat and changing your mind does not litter the list
  //  with empty conversations.
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saved, setSaved] = useState<ConversationList | null>(null);
  //: Pictures staged for the next message. Data URLs, so a file the user
  //  moves or deletes afterwards does not empty the conversation later.
  const [attached, setAttached] = useState<string[]>([]);
  const [visionOk, setVisionOk] = useState(false);
  //: What is being fetched right now, and what has been. A conversation that
  //  reaches the internet has to say so while it happens — this is the one
  //  thing in an otherwise offline application that leaves the machine.
  const [looking, setLooking] = useState<string[]>([]);
  const [consulted, setConsulted] = useState<string[]>([]);
  const [input, setInput] = useState('');
  const [generating, setGenerating] = useState(false);
  const chatAbort = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
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

  //: Hands-free conversation. Held in a ref because it owns a microphone and
  //  an audio graph, and both have to be released on unmount whatever else
  //  happens.
  const conversation = useRef<Conversation | null>(null);
  //: The loop is built once and lives across renders, while `send` closes over
  //  state that changes every keystroke. The ref is what keeps the loop calling
  //  the CURRENT send rather than the one that existed when it started.
  const sendRef = useRef<(text: string, speak: boolean) => Promise<void>>(
    async () => {});
  const [conversing, setConversing] = useState(false);
  //: The conversation loop has no transcript of its own to fail into — a
  //  microphone that was refused has to say so somewhere.
  const [lastError, setLastError] = useState<string | null>(null);
  const [heard, setHeard] = useState<'listening' | 'hearing' | 'thinking' | 'speaking' | 'off'>('off');

  const [web, setWeb] = useState(() => {
    try { return localStorage.getItem('uncloud.chat.web') !== 'off'; }
    catch { return true; }
  });
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
    engineStatus().then((s) => {
      if (s.running && s.model_path) {
        setActiveModel((prev) => prev ?? {
          id: s.model_path!, name: s.model_path!.split('/').pop()!, category: 'text',
          engine: s.engine!, path: s.model_path!, size_gb: 0, catalog_id: null,
          tags: [], ready: true, note: null, capabilities: ['text2img'],
        });
      }
    });
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function selectModel(model: LocalModel) {
    setPickerOpen(false);
    setLoadingModel(true);
    try {
      await startEngine(model.path, model.engine);
      setActiveModel(model);
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

  async function renderPreviews(index: number, reply: string) {
    // The switch holds regardless of what the model wrote. A model told not to
    // draw will still occasionally draw, and the user's setting has to win
    // that argument rather than merely take part in it.
    if (!pictures) return;
    const prompts = [...reply.matchAll(IMAGE_MARKER)]
      .map((mm) => mm[1].trim())
      .slice(0, 2);
    if (!prompts.length) return;
    setPreviews((p) => ({ ...p, [index]: prompts.map((prompt) => ({ prompt })) }));
    for (let i = 0; i < prompts.length; i++) {
      try {
        const { url, path } = await quickImagePreview(prompts[i]);
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
            copy[index] = { ...turn, drew: [...(turn.drew ?? []), { prompt: prompts[i], path }] };
            if (conversationId) void persist(conversationId, copy);
            return copy;
          });
        }
      } catch (e) {
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
  const toggleConversation = useCallback(async () => {
    if (conversation.current?.active) {
      conversation.current.stop();
      conversation.current = null;
      setConversing(false);
      return;
    }
    const loop = new Conversation({
      onState: setHeard,
      onError: (message) => { setLastError(message); setConversing(false); },
      onUtterance: async (audio) => {
        // The same speech-to-text model dictation already uses; the loop is
        // a different way of reaching it, not a second engine.
        if (!sttModel) return;
        const said = await transcribeAudio(sttModel.path, audio, 'turn.webm');
        if (!said.trim()) return;
        // Spoken aloud, and the reply is spoken back — which is what makes
        // this a conversation rather than dictation into a text box.
        await sendRef.current(said, true);
      },
    });
    conversation.current = loop;
    setConversing(true);
    setAutoSpeak(true);
    await loop.start();
  }, []);

  // The microphone must not outlive the view. Nothing else releases it, and a
  // recording indicator that stays lit is alarming and correct to be alarmed by.
  useEffect(() => () => {
    conversation.current?.stop();
    conversation.current = null;
  }, []);

  useEffect(() => { sendRef.current = send; });

  const refreshSaved = useCallback(
    () => listConversations().then(setSaved).catch(() => {}), []);
  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  /** Write the conversation to disk.
   *
   *  Called after each reply rather than on a timer or at quit: a crash, a
   *  force-quit and a flat battery all skip anything scheduled for later, and
   *  those are exactly the moments this exists for.
   */
  const persist = useCallback(async (id: string, turns: ChatMessage[]) => {
    if (!turns.length) return;
    try {
      await writeConversation(id, { messages: turns, model_path: activeModel?.path ?? null });
      refreshSaved();
    } catch {
      // Saving is not the user's job to supervise. A failure here must not
      // interrupt a conversation that is otherwise working.
    }
  }, [activeModel, refreshSaved]);

  const startNew = useCallback(() => {
    setMessages([]);
    setPreviews({});
    setConversationId(null);
    setAttached([]);
    setInput('');
  }, []);

  const openSaved = useCallback(async (id: string) => {
    try {
      const conversation = await readConversation(id);
      // Stored as the model wrote it, tags and all. Splitting on load rather
      // than on save keeps the file a faithful record of the reply, and means
      // a conversation saved before this existed opens correctly too.
      void loadDrawn(conversation.messages);
      setMessages(conversation.messages.map((m) => {
        if (m.role !== 'assistant' || m.reasoning) return m;
        const { thinking, answer } = splitThinking(m.content);
        return thinking ? { ...m, content: answer, reasoning: thinking } : m;
      }));
      setConversationId(conversation.id);
      setAttached([]);
    } catch {
      // A conversation that will not decrypt is already reported in the list;
      // failing to open it must not blank the one on screen.
    }
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

  const attachImages = useCallback(() => {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/*';
    picker.multiple = true;
    picker.onchange = () => {
      for (const file of Array.from(picker.files ?? [])) {
        const reader = new FileReader();
        reader.onload = () => {
          const url = String(reader.result || '');
          if (url.startsWith('data:image/')) setAttached((a) => [...a, url]);
        };
        reader.readAsDataURL(file);
      }
    };
    picker.click();
  }, []);

  async function send(text: string, speakReply: boolean) {
    // A picture on its own is a perfectly good question — "what is this?" is
    // implied — so an empty box with an attachment still sends.
    if ((!text.trim() && !attached.length) || !activeModel || generating) return;
    const images = attached;
    const next = [...messages, {
      role: 'user', content: text.trim(), ...(images.length ? { images } : {}),
    } as ChatMessage];
    setMessages(next);
    setAttached([]);
    setInput('');
    setConsulted([]);
    setLooking([]);
    setGenerating(true);
    setMessages((m) => [...m, { role: 'assistant', content: '' }]);
    let full = '';
    const controller = new AbortController();
    chatAbort.current = controller;
    try {
      // Generating an image frees the chat engine to make room — reload it transparently if needed.
      const status = await engineStatus();
      if (!status.running || status.model_path !== activeModel.path) {
        await startEngine(activeModel.path, activeModel.engine);
      }
      const assistantIndex = next.length;
      //: The turns actually sent. It grows when the model asks to look
      //  something up, so its own request and the results are both in context
      //  for the answer that follows.
      let sent: ChatMessage[] = [...next];

      for (let round = 0; ; round++) {
        full = '';
        for await (const chunk of streamChat(
          [{ role: 'system', content: chatSystemPrompt({ pictures, web, manner }) }, ...sent],
          controller.signal,
        )) {
          if (chunk.kind === 'text') full += chunk.text;
          setMessages((m) => {
            const copy = [...m];
            const prev = copy[copy.length - 1];
            copy[copy.length - 1] = chunk.kind === 'thinking'
              ? { ...prev, reasoning: (prev.reasoning ?? '') + chunk.text }
              : { ...prev, content: prev.content + chunk.text };
            return copy;
          });
        }

        // With pictures off, a model that asks for one anyway is simply not
        // given one — the switch has to hold whatever the model does with the
        // prompt, or it is not a switch.
        // Both switches hold whatever the model wrote. A model told it is
        // offline will occasionally ask to search anyway, and the setting has
        // to win that argument rather than merely take part in it.
        const wanted = web
          ? findLookups(full).filter((l) => pictures || l.kind !== 'pictures')
          : [];
        if (!wanted.length) break;

        // A model that searches, reads, and searches again is working. One
        // that searches for ever is not, and without a ceiling it would do so
        // while the user watched.
        if (round >= MAX_ROUNDS - 1) {
          setMessages((m) => {
            const copy = [...m];
            const prev = copy[copy.length - 1];
            copy[copy.length - 1] = {
              ...prev,
              content: `${stripLookups(prev.content)}\n\n_Stopped after `
                + `${MAX_ROUNDS} lookups without an answer._`,
            };
            return copy;
          });
          break;
        }

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
                text: images.length
                  ? `${images.length} pictures are now displayed to the user. `
                    + 'Refer to them naturally; do not describe their contents, '
                    + 'because you cannot see them.'
                  : 'No pictures were found. Say so.',
              };
            }
            const text = lookup.kind === 'search'
              ? (await webSearch(lookup.argument)).results
              : (await webRead(lookup.argument)).text;
            return { lookup, text };
          } catch (e) {
            // A failed lookup is reported to the MODEL, not swallowed, so it
            // can say the search did not work rather than inventing an answer.
            return { lookup, text: `This lookup failed: ${
              e instanceof Error ? e.message : String(e)}` };
          }
        }));
        setLooking([]);
        setConsulted((c) => [...c, ...wanted.map((l) => l.argument)]);
        if (shown.length) {
          setMessages((m) => {
            const copy = [...m];
            const prev = copy[copy.length - 1];
            copy[copy.length - 1] = { ...prev, found: [...(prev.found ?? []), ...shown] };
            return copy;
          });
        }

        // The request stays in the transcript the model sees — without it the
        // results arrive as an answer to nothing.
        sent = [
          ...sent,
          { role: 'assistant', content: full },
          { role: 'user', content: resultsTurn(fetched) },
        ];
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { ...copy[copy.length - 1], content: '' };
          return copy;
        });
      }

      // The markers were an instruction to the application, not part of the
      // answer. Left in, the user reads the plumbing.
      full = stripLookups(full);
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { ...copy[copy.length - 1], content: full };
        return copy;
      });
      // Fire and forget: the reply is already readable, and a preview
      // takes seconds during which the user should not be blocked.
      void renderPreviews(assistantIndex, full);

      // Saved now the exchange is complete. The id is minted on the first
      // save rather than when the view opens, so opening Chat and changing
      // your mind does not leave an empty conversation in the list.
      const id = conversationId ?? newConversationId();
      if (!conversationId) setConversationId(id);
      void persist(id, [...next, { role: 'assistant', content: full } as ChatMessage]);

      if (speakReply && full.trim()) {
        setSpeaking(true);
        try {
          const url = await speakText(full.trim(), voice);
          if (audioRef.current) {
            audioRef.current.src = url;
            // Deaf while it talks, or the reply becomes the next question and
            // it converses with itself until stopped.
            conversation.current?.setSpeaking(true);
            try {
              await audioRef.current.play();
              await new Promise<void>((resolve) => {
                const done = () => resolve();
                audioRef.current!.onended = done;
                audioRef.current!.onerror = done;
              });
            } finally {
              conversation.current?.setSpeaking(false);
            }
          }
        } finally {
          setSpeaking(false);
        }
      }
    } catch (e) {
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
        setMessages((m) => [...m, { role: 'assistant', content: `⚠ ${e}` }]);
      }
    } finally {
      chatAbort.current = null;
      setGenerating(false);
    }
  }

  function stopGenerating() {
    chatAbort.current?.abort();
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

  // The field grows with what is typed, to a ceiling, then scrolls. Unbounded
  // growth would push the conversation off the top of the screen, which is the
  // opposite of what a bigger field is for.
  const field = useRef<HTMLTextAreaElement>(null);
  const resize = useCallback(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = 'auto';               // reset, or it can only ever grow
    el.style.height = `${Math.min(el.scrollHeight, window.innerHeight * 0.4)}px`;
  }, []);
  useLayoutEffect(resize, [input, messages.length, resize]);
  useEffect(() => {
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, [resize]);

  const empty = messages.length === 0;

  const composer = (
    <div className="composer-inner">
      <div className="composer-card">
        {/* What is going with the next message. Shown before sending, and
            removable: attaching the wrong screenshot is easy and noticing
            after the model has answered is too late. */}
        {attached.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1 pb-2">
            {attached.map((url, i) => (
              <div key={i} className="relative">
                <img src={url} alt="" className="h-14 w-14 object-cover rounded-lg
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
          </div>
        )}
        <textarea
          ref={field}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send(input, autoSpeak);
            }
          }}
          placeholder={activeModel ? 'Ask anything' : 'Ask anything — pick a model above to send'}
          // Deliberately NOT disabled. Writing a question while a model is
          // still loading is normal; a field that refuses input reads as a
          // broken application rather than as a precondition. Only sending is
          // gated.
          rows={1}
          className="composer-input"
        />

        <div className="composer-actions">
          {sttModel && (
            <button
              onClick={recording ? stopRecording : startRecording}
              disabled={!activeModel || transcribing}
              title={recording ? 'Stop recording' : `Dictate with ${sttModel.name}`}
              aria-label={recording ? 'Stop recording' : 'Dictate'}
              className={recording ? 'pill pill-icon pill-on' : 'pill pill-icon'}
              style={recording ? { color: 'var(--danger)' } : undefined}
            >
              {transcribing ? <Loader2 size={14} className="animate-spin" />
                : recording ? <Square size={11} fill="currentColor" />
                : <Mic size={15} />}
            </button>
          )}

          {/* Attaching a picture. Offered whatever the model, and refused with
              a reason when it cannot see — hiding the button would leave
              somebody hunting for a feature that is present. */}
          <button
            onClick={attachImages}
            disabled={!activeModel || !visionOk}
            title={visionOk
              ? 'Attach an image for the model to look at'
              : 'This model is text-only and cannot see images. Load a vision model '
                + '(its name usually says VL or Vision) from the Models tab.'}
            aria-label="Attach an image"
            className="pill pill-icon"
          >
            <ImagePlus size={15} />
          </button>

          {/* The only control here that governs the network. Labelled plainly,
              because "local-first" is the promise this application makes and
              an exception to it should be visible rather than discovered. */}
          <button
            onClick={() => setWeb((v) => !v)}
            title={web
              ? 'Web lookups: on — search queries are sent to DuckDuckGo when '
                + 'the model asks to look something up. Nothing else leaves this Mac.'
              : 'Web lookups: off — nothing leaves this Mac'}
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
            {speaking ? <Loader2 size={14} className="animate-spin" />
              : autoSpeak ? <Volume2 size={15} /> : <VolumeX size={15} />}
            <span>Speak</span>
          </button>

          {/* Hands-free. The state is written out rather than left to a colour,
              because "is it listening to me right now" is the one question a
              voice interface must never leave ambiguous. */}
          {sttModel && (
            <button
              onClick={toggleConversation}
              disabled={!activeModel}
              title={conversing
                ? 'Stop the conversation'
                : 'Talk instead of typing — it listens, answers aloud, and listens again'}
              className={conversing ? 'pill pill-on' : 'pill'}
              style={conversing ? { color: 'var(--accent)' } : undefined}
            >
              {conversing ? <AudioLines size={15} className="animate-pulse" />
                : <MessagesSquare size={15} />}
              <span>
                {!conversing ? 'Converse'
                  : heard === 'hearing' ? 'Listening…'
                  : heard === 'thinking' ? 'Thinking…'
                  : heard === 'speaking' ? 'Speaking…'
                  : 'Your turn'}
              </span>
            </button>
          )}

          {/* Voice and manner. Behind a menu: they are set once and then left
              alone, and a row of pickers would crowd the things used every
              message. */}
          <details className="relative">
            <summary className="pill list-none cursor-pointer select-none"
                     title="How replies sound">
              <Settings2 size={14} /><span>Voice</span>
            </summary>
            <div className="absolute bottom-full mb-2 left-0 z-40 card p-2
                            flex flex-col gap-3" style={{ minWidth: 240 }}>
              <label className="field">
                <span className="label" style={{ fontSize: 11 }}>Voice</span>
                <select className="input" value={voice}
                        onChange={(e) => setVoice(e.target.value)}>
                  {VOICES.map((v) => (
                    <option key={v.id} value={v.id}>{v.label}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="label" style={{ fontSize: 11 }}>Manner</span>
                <select className="input" value={manner}
                        onChange={(e) => setManner(e.target.value)}>
                  {MANNERS.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </label>
              <p className="faint" style={{ fontSize: 10, lineHeight: 1.5 }}>
                Manner changes how the assistant writes, so it reads well aloud —
                short sentences, no lists or markdown. The voice is one of the
                nine that ship with the app.
              </p>
            </div>
          </details>

          {/* Hand the conversation to Chisel. Only once there is something to
              hand over, and never while the model is still writing — the last
              message is what becomes the goal, and half of it is not a goal. */}
          {messages.some((m) => m.role === 'user') && (
            <button
              onClick={() => sendToChisel(fromConversation(messages))}
              disabled={generating}
              title="Continue this in Chisel, carrying the conversation"
              className="pill"
            >
              <Hammer size={15} />
              <span>Chisel</span>
            </button>
          )}

          <div className="composer-spacer" />

          <button
            onClick={generating ? stopGenerating : () => send(input, autoSpeak)}
            disabled={!activeModel || (!generating && !input.trim() && !attached.length)}
            title={generating ? 'Stop response' : 'Send'}
            aria-label={generating ? 'Stop response' : 'Send'}
            className="composer-send"
          >
            {generating ? <Square size={12} fill="currentColor" /> : <ArrowUp size={17} />}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="h-full flex flex-col relative">
      {/* The model in play is the window's context, so it lives in the title
          bar rather than in a header of this view's own. */}
      <TitleBarPortal>
        <div style={{ position: 'relative' }}>
          <button className="tb-context" onClick={() => setPickerOpen((v) => !v)}
                  aria-haspopup="listbox" aria-expanded={pickerOpen}>
            {loadingModel ? (
              <><span className="spinner" /><span>Loading model…</span></>
            ) : activeModel ? (
              <>
                <span style={{
                  width: 6, height: 6, borderRadius: 999,
                  background: 'var(--success)', flex: 'none',
                }} />
                <span>{activeModel.name}</span>
              </>
            ) : (
              <span style={{ color: 'var(--text-3)' }}>Select model</span>
            )}
            <ChevronDown size={15} style={{ flex: 'none', color: 'var(--text-3)' }} />
          </button>

          {pickerOpen && (
            <div
              className="card no-drag chassis-scroll"
              role="listbox"
              style={{
                position: 'absolute', top: 36, left: 0, zIndex: 50,
                width: 340, maxHeight: 320, padding: 6,
                boxShadow: 'var(--shadow-lg)',
              }}
            >
              {models.length === 0 && (
                <div style={{
                  fontSize: 'var(--text-xs)', color: 'var(--text-3)',
                  padding: '16px 12px', textAlign: 'center',
                }}>
                  No text models yet. Download one from the Models tab.
                </div>
              )}
              {models.map((m) => (
                <button key={m.id} onClick={() => selectModel(m)} role="option"
                        aria-selected={activeModel?.id === m.id} className="menu-row">
                  <span>{m.name}</span>
                  <span className="font-mono" style={{
                    fontSize: 10, color: 'var(--text-3)',
                    textTransform: 'uppercase', flex: 'none',
                  }}>{m.engine}</span>
                </button>
              ))}
            </div>
          )}
        </div>

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
      </TitleBarPortal>

      {empty ? (
        /* Nothing to read yet, so the composer IS the page. */
        <div className="composer composer-centred">
          <div className="greeting">
            <Mark px={38} />
            <span>What are we making?</span>
          </div>
          {composer}
        </div>
      ) : (
        <>
          <div ref={scrollRef} className="flex-1 chassis-scroll" style={{ padding: '8px 24px 0' }}>
            <div className="column flex flex-col gap-5 py-4">
            {messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'self-end max-w-[80%]' : 'self-start max-w-[85%]'}>
                {/* A reasoning model produces most of its tokens here before
                    answering. Hidden, it reads as a hung app; shown in full it
                    buries the answer. Collapsed, with a live hint while it is
                    still thinking. */}
                {m.role === 'assistant' && m.reasoning && (
                  <details className="mb-1.5 px-1 group">
                    <summary className="text-[11px] text-[var(--text-faint)] cursor-pointer select-none hover:text-[var(--text-dim)] transition">
                      {m.content ? 'Thought before answering' : 'Thinking…'}
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
                    <div className="whitespace-pre-wrap">
                      {m.content.replace(IMAGE_MARKER, '').trimEnd()}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-[var(--text)] px-1">
                    {(() => {
                      const shown = m.content.replace(IMAGE_MARKER, '').trimEnd();
                      if (shown) return <Markdown>{shown}</Markdown>;
                      // Still arriving.
                      if (i === messages.length - 1 && generating && !m.reasoning) {
                        return <span className="spinner" />;
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
                      if (m.reasoning) {
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
                    <span>Looked up: {consulted.join(' · ')}</span>
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
                        <span className="spinner" />
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
