import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ArrowUp, Square, Mic, Volume2, VolumeX, Loader2 } from 'lucide-react';
import { TitleBarPortal } from '../components/TitleBar';
import { Cog } from '../components/Wordmark';
import { getLibrary, startEngine, engineStatus, streamChat, transcribeAudio, speakText, IMAGE_MARKER, CHAT_IMAGE_SYSTEM_PROMPT, quickImagePreview} from '../lib/sidecar';
import type { LocalModel, ChatMessage } from '../lib/sidecar';

export default function ChatView() {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [activeModel, setActiveModel] = useState<LocalModel | null>(null);
  const [loadingModel, setLoadingModel] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [generating, setGenerating] = useState(false);
  const chatAbort = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(false);
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

  async function renderPreviews(index: number, reply: string) {
    const prompts = [...reply.matchAll(IMAGE_MARKER)]
      .map((mm) => mm[1].trim())
      .slice(0, 2);
    if (!prompts.length) return;
    setPreviews((p) => ({ ...p, [index]: prompts.map((prompt) => ({ prompt })) }));
    for (let i = 0; i < prompts.length; i++) {
      try {
        const url = await quickImagePreview(prompts[i]);
        setPreviews((p) => {
          const row = [...(p[index] || [])];
          row[i] = { ...row[i], url };
          return { ...p, [index]: row };
        });
      } catch (e) {
        setPreviews((p) => {
          const row = [...(p[index] || [])];
          row[i] = { ...row[i], error: String(e).replace(/^Error:\s*/, '') };
          return { ...p, [index]: row };
        });
      }
    }
  }

  async function send(text: string, speakReply: boolean) {
    if (!text.trim() || !activeModel || generating) return;
    const next = [...messages, { role: 'user', content: text.trim() } as ChatMessage];
    setMessages(next);
    setInput('');
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
      const withSystem: ChatMessage[] = [
        { role: 'system', content: CHAT_IMAGE_SYSTEM_PROMPT },
        ...next,
      ];
      for await (const chunk of streamChat(withSystem, controller.signal)) {
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
      // Fire and forget: the reply is already readable, and a preview
      // takes seconds during which the user should not be blocked.
      void renderPreviews(assistantIndex, full);

      if (speakReply && full.trim()) {
        setSpeaking(true);
        try {
          const url = await speakText(full.trim());
          if (audioRef.current) {
            audioRef.current.src = url;
            await audioRef.current.play();
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

          <div className="composer-spacer" />

          <button
            onClick={generating ? stopGenerating : () => send(input, autoSpeak)}
            disabled={!activeModel || (!generating && !input.trim())}
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
    <div className="h-full flex flex-col">
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
      </TitleBarPortal>

      {empty ? (
        /* Nothing to read yet, so the composer IS the page. */
        <div className="composer composer-centred">
          <div className="greeting">
            <Cog px={32} />
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
                <div
                  className={
                    m.role === 'user'
                      ? 'bg-[var(--bg-raised)] border border-[var(--border)] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm'
                      : 'text-sm text-[var(--text)] whitespace-pre-wrap leading-relaxed px-1'
                  }
                >
                  {m.content.replace(IMAGE_MARKER, '').trimEnd()
                    || (m.reasoning ? null : <span className="spinner" />)}
                </div>
                {(previews[i] || []).map((p, k) => (
                  <div key={k} className="mt-2 max-w-[280px]">
                    {p.url ? (
                      <img
                        src={p.url}
                        alt={p.prompt}
                        className="w-full rounded-lg border border-[var(--border)]"
                      />
                    ) : p.error ? (
                      <div className="text-[11px] text-rose-400 px-1">{p.error}</div>
                    ) : (
                      <div className="h-[140px] rounded-lg bg-[var(--bg-inset)] flex items-center justify-center">
                        <span className="spinner" />
                      </div>
                    )}
                    <p className="mt-1 text-[10px] text-[var(--text-faint)] leading-relaxed px-1">
                      Quick preview — 6 steps at 512px, for thinking with. Use the Image
                      tab for anything you intend to keep.
                    </p>
                  </div>
                ))}
              </div>
            ))}
            </div>
          </div>

          <div className="composer composer-docked">{composer}</div>
        </>
      )}

      <audio ref={audioRef} className="hidden" />
    </div>
  );
}
