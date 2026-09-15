import { useEffect, useRef, useState } from 'react';
import { Mic, Square, Loader2, ChevronDown } from 'lucide-react';
import { getLibrary, transcribeAudio } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';

export default function VoiceTools() {
  const [sttModels, setSttModels] = useState<LocalModel[]>([]);
  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState('');

  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => {
    getLibrary().then((list) => {
      const stt = list.filter((m) => m.category === 'voice-stt' && m.ready);
      setSttModels(stt);
      setSttModel(stt[0] ?? null);
    });
  }, []);

  async function startRecording() {
    setTranscript('');
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
        setTranscript(text);
      } catch (e) {
        setTranscript(`⚠ ${e}`);
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
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="grid grid-cols-1 gap-5 max-w-xl">
        <section className="card p-5 flex flex-col gap-4">
          <h2 className="text-sm font-medium">Transcribe</h2>

          <div className="relative">
            <button
              onClick={() => setPickerOpen((v) => !v)}
              className="w-full flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-[var(--bg-inset)] hover:bg-[var(--bg-inset)]/70 transition"
            >
              <span className={sttModel ? '' : 'text-[var(--text-faint)]'}>
                {sttModel ? sttModel.name : 'No speech-to-text model installed'}
              </span>
              <ChevronDown size={13} className="text-[var(--text-faint)]" />
            </button>
            {pickerOpen && sttModels.length > 0 && (
              <div className="absolute top-9 left-0 right-0 card p-1.5 z-10 shadow-2xl">
                {sttModels.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => { setSttModel(m); setPickerOpen(false); }}
                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition text-sm"
                  >
                    {m.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={recording ? stopRecording : startRecording}
            disabled={!sttModel || transcribing}
            className={`h-12 rounded-xl flex items-center justify-center gap-2 text-sm transition disabled:opacity-40 ${
              recording ? 'bg-rose-950/50 text-rose-300 border border-rose-900/50' : 'bg-[var(--bg-inset)] hover:bg-[var(--bg-inset)]/70'
            }`}
          >
            {recording ? <Square size={14} fill="currentColor" /> : <Mic size={16} />}
            {recording ? 'Stop recording' : 'Start recording'}
          </button>

          <div className="min-h-[80px] text-sm text-[var(--text-dim)] leading-relaxed">
            {transcribing ? (
              <span className="flex items-center gap-2 text-[var(--text-faint)]"><Loader2 size={14} className="animate-spin" /> Transcribing…</span>
            ) : transcript || <span className="text-[var(--text-faint)]">Your transcript will appear here.</span>}
          </div>
        </section>

      </div>
    </div>
  );
}
