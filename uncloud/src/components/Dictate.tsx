import ActivityOrb from './ActivityOrb';
import { useEffect, useRef, useState } from 'react';
import { Mic } from 'lucide-react';
import { getLibrary, transcribeAudio } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';
import { onLibraryChange } from '../lib/library-changed';

/**
 * Dictation for any text field. Records while held open, transcribes locally
 * with whichever speech-to-text model is installed, and appends the result to
 * whatever is already written rather than replacing it — a half-typed prompt
 * should survive being finished out loud.
 *
 * Renders nothing when no speech-to-text model is installed; an always-visible
 * button that always fails would be worse than no button.
 */

// One scan shared by every instance. A field-level component mounted a dozen
// times should not trigger a dozen library scans.
let cached: Promise<LocalModel | null> | null = null;
function sttModel(): Promise<LocalModel | null> {
  if (!cached) {
    cached = getLibrary()
      .then((ms) => ms.find((m) => m.category === 'voice-stt') ?? null)
      .catch(() => null);
  }
  return cached;
}

export default function Dictate({
  onText,
  title = 'Dictate',
  className = '',
}: {
  onText: (text: string) => void;
  title?: string;
  className?: string;
}) {
  const [model, setModel] = useState<LocalModel | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => {
    const refresh = () => { cached = null; sttModel().then(setModel); };
    refresh();
    return onLibraryChange(refresh);
  }, []);

  // Releasing the microphone matters: the OS shows a recording indicator for as
  // long as the track is live, even if this component is gone.
  useEffect(() => () => {
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  if (!model) return null;

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunks.current = [];
      rec.ondataavailable = (e) => chunks.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setBusy(true);
        try {
          const blob = new Blob(chunks.current, { type: 'audio/webm' });
          const text = await transcribeAudio(model!.path, blob);
          if (text.trim()) onText(text.trim());
        } catch {
          /* a failed transcription should not take the field with it */
        } finally {
          setBusy(false);
        }
      };
      rec.start();
      recorder.current = rec;
      setRecording(true);
    } catch {
      setRecording(false);   // permission refused, or no microphone
    }
  }

  function stop() {
    recorder.current?.stop();
    setRecording(false);
  }

  return (
    <button
      type="button"
      onClick={recording ? stop : start}
      disabled={busy}
      title={recording ? 'Stop and transcribe' : title}
      aria-label={recording ? 'Stop and transcribe' : title}
      className={`shrink-0 w-7 h-7 rounded-lg flex items-center justify-center transition ${
        recording
          ? 'accent-bar text-white'
          : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]'
      } disabled:opacity-40 ${className}`}
    >
      {busy ? <ActivityOrb state="working" size={20} label="Working…" /> : <Mic size={13} />}
    </button>
  );
}
