import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Send, Square, Mic, Volume2, VolumeX, Loader2 } from 'lucide-react';
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
      for await (const chunk of streamChat(withSystem)) {
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
      setMessages((m) => [...m, { role: 'assistant', content: `⚠ ${e}` }]);
    } finally {
      setGenerating(false);
    }
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

  return (
    <div className="h-full flex flex-col">
      <header className="h-14 shrink-0 border-b border-[var(--border-soft)] flex items-center px-5 relative">
        <button
          className="flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg hover:bg-[var(--bg-raised)] transition"
          onClick={() => setPickerOpen((v) => !v)}
        >
          {loadingModel ? (
            <span className="flex items-center gap-2 text-[var(--text-dim)]"><span className="spinner" /> Loading model…</span>
          ) : activeModel ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span>{activeModel.name}</span>
            </>
          ) : (
            <span className="text-[var(--text-faint)]">Select a model</span>
          )}
          <ChevronDown size={14} className="text-[var(--text-faint)]" />
        </button>

        {pickerOpen && (
          <div className="absolute top-14 left-5 w-96 card p-1.5 z-10 shadow-2xl max-h-80 overflow-y-auto">
            {models.length === 0 && (
              <div className="text-xs text-[var(--text-faint)] px-3 py-4 text-center">
                No text models found yet. Download one from the Models tab.
              </div>
            )}
            {models.map((m) => (
              <button
                key={m.id}
                onClick={() => selectModel(m)}
                className="w-full text-left px-3 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition flex items-center justify-between"
              >
                <span className="text-sm">{m.name}</span>
                <span className="text-[10px] font-mono text-[var(--text-faint)] uppercase">{m.engine}</span>
              </button>
            ))}
          </div>
        )}

        <button
          onClick={() => setAutoSpeak((v) => !v)}
          title={autoSpeak ? 'Auto-speak replies: on' : 'Auto-speak replies: off'}
          className={`ml-auto w-8 h-8 rounded-lg flex items-center justify-center transition ${
            autoSpeak ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50'
          }`}
        >
          {speaking ? <Loader2 size={14} className="animate-spin" /> : autoSpeak ? <Volume2 size={14} /> : <VolumeX size={14} />}
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[var(--text-faint)] text-sm">
            {activeModel ? 'Say something to get started.' : 'Pick a model above to start chatting.'}
          </div>
        ) : (
          <div className="max-w-2xl mx-auto flex flex-col gap-5">
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
        )}
      </div>

      <div className="p-4 border-t border-[var(--border-soft)]">
        <div className="max-w-2xl mx-auto flex items-end gap-2 card px-3 py-2 focus-within:border-[#3a3a42]">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send(input, autoSpeak);
              }
            }}
            placeholder={activeModel ? 'Message Uncloud…' : 'Load a model first'}
            disabled={!activeModel}
            rows={1}
            className="flex-1 bg-transparent outline-none resize-none text-sm py-1.5 placeholder:text-[var(--text-faint)] max-h-40"
          />
          {sttModel && (
            <button
              onClick={recording ? stopRecording : startRecording}
              disabled={!activeModel || transcribing}
              title={sttModel.name}
              className={`w-8 h-8 rounded-full flex items-center justify-center transition shrink-0 disabled:opacity-30 ${
                recording ? 'bg-rose-950/60 text-rose-300' : 'bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white'
              }`}
            >
              {transcribing ? <Loader2 size={13} className="animate-spin" /> : recording ? <Square size={11} fill="currentColor" /> : <Mic size={14} />}
            </button>
          )}
          <button
            onClick={() => send(input, autoSpeak)}
            disabled={!activeModel || !input.trim() || generating}
            className="w-8 h-8 rounded-full btn-accent flex items-center justify-center disabled:opacity-30 transition shrink-0"
          >
            {generating ? <Square size={12} fill="currentColor" /> : <Send size={14} />}
          </button>
        </div>
      </div>
      <audio ref={audioRef} className="hidden" />
    </div>
  );
}
