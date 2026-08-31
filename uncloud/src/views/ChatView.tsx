import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Send, Square, Mic, Volume2, VolumeX, Loader2 } from 'lucide-react';
import { getLibrary, startEngine, engineStatus, streamChat, transcribeAudio, speakText } from '../lib/sidecar';
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
      for await (const token of streamChat(next)) {
        full += token;
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { role: 'assistant', content: copy[copy.length - 1].content + token };
          return copy;
        });
      }
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
                <div
                  className={
                    m.role === 'user'
                      ? 'bg-[var(--bg-raised)] border border-[var(--border)] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm'
                      : 'text-sm text-[var(--text)] whitespace-pre-wrap leading-relaxed px-1'
                  }
                >
                  {m.content || <span className="spinner" />}
                </div>
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
