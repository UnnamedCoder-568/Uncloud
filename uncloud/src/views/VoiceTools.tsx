import { useEffect, useRef, useState } from 'react';
import { Mic, Square, Volume2, Loader2, ChevronDown } from 'lucide-react';
import { getLibrary, transcribeAudio, speakText, listVoices } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';

export default function VoiceTools() {
  const [sttModels, setSttModels] = useState<LocalModel[]>([]);
  const [sttModel, setSttModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState('');

  const [speakInput, setSpeakInput] = useState('');
  const [voices, setVoices] = useState<string[]>([]);
  const [voice, setVoice] = useState('af_heart');
  const [synthesizing, setSynthesizing] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => {
    getLibrary().then((list) => {
      const stt = list.filter((m) => m.category === 'voice-stt' && m.ready);
      setSttModels(stt);
      setSttModel(stt[0] ?? null);
    });
    listVoices().then(setVoices).catch(() => setVoices(['af_heart']));
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

  async function synthesize() {
    if (!speakInput.trim()) return;
    setSynthesizing(true);
    setAudioUrl(null);
    try {
      setAudioUrl(await speakText(speakInput.trim(), voice));
    } finally {
      setSynthesizing(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="grid grid-cols-2 gap-5 max-w-4xl">
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

        <section className="card p-5 flex flex-col gap-4">
          <h2 className="text-sm font-medium">Speak</h2>

          <select
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            className="text-xs px-3 py-2 rounded-lg bg-[var(--bg-inset)] outline-none"
          >
            {voices.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>

          <textarea
            value={speakInput}
            onChange={(e) => setSpeakInput(e.target.value)}
            placeholder="Type something for Uncloud to say…"
            rows={4}
            className="bg-[var(--bg-inset)] rounded-lg px-3 py-2 text-sm outline-none resize-none placeholder:text-[var(--text-faint)]"
          />

          <button
            onClick={synthesize}
            disabled={!speakInput.trim() || synthesizing}
            className="h-10 rounded-xl bg-white text-black text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 disabled:bg-[var(--border)] disabled:text-[var(--text-faint)] transition"
          >
            {synthesizing ? <Loader2 size={14} className="animate-spin" /> : <Volume2 size={14} />}
            {synthesizing ? 'Synthesizing…' : 'Speak'}
          </button>

          {audioUrl && <audio src={audioUrl} controls autoPlay className="w-full h-9" />}
        </section>
      </div>
    </div>
  );
}
