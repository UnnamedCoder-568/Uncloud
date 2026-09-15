import { useEffect, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';

/**
 * Record a short clip from the microphone and hand back the audio.
 *
 * Stops on its own at `maxSeconds`: a reference voice needs ten seconds or so,
 * and a recording nobody remembered to stop is a minute of room noise.
 * The seconds are counted on the button, because "is it still recording" must
 * never be left to a colour.
 */
export default function RecordButton({
  onRecorded,
  maxSeconds = 20,
  label = 'Record',
  disabled = false,
}: {
  onRecorded: (audio: Blob) => void;
  maxSeconds?: number;
  label?: string;
  disabled?: boolean;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);

  function clear() {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
  }

  // The microphone must not outlive the control that opened it.
  useEffect(() => () => {
    clear();
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  async function start() {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError('Uncloud could not open the microphone. Allow access in System Settings '
        + '→ Privacy & Security → Microphone.');
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clear();
      setRecording(false);
      if (chunks.length) onRecorded(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
    };
    rec.start();
    recorder.current = rec;
    setSeconds(0);
    setRecording(true);
    const began = performance.now();
    timer.current = window.setInterval(() => {
      const s = Math.floor((performance.now() - began) / 1000);
      setSeconds(s);
      if (s >= maxSeconds && rec.state !== 'inactive') rec.stop();
    }, 250);
  }

  function stop() {
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop();
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={recording ? stop : start}
        disabled={disabled && !recording}
        className={recording ? 'pill pill-on' : 'pill'}
        style={recording ? { color: 'var(--danger)' } : undefined}
        title={recording ? 'Stop recording' : `Record up to ${maxSeconds} seconds`}
      >
        {recording ? <Square size={11} fill="currentColor" /> : <Mic size={14} />}
        <span className="tabular-nums">{recording ? `Stop · ${seconds}s` : label}</span>
      </button>
      {error && <p className="text-[10px] text-rose-400 leading-relaxed">{error}</p>}
    </div>
  );
}
