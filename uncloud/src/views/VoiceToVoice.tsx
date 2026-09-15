import { useEffect, useRef, useState } from 'react';
import { Loader2, Mic, MicOff, Repeat, Upload } from 'lucide-react';
import {
  chatSystemPrompt, engineStatus, getLibrary, speechClipUrl, speechEngines, speechJob,
  startConversion, startEngine, streamChat, uploadRecording,
} from '../lib/sidecar';
import type { ChatMessage, LocalModel, SpeechJob, SpeechModel } from '../lib/sidecar';
import { describeTalk, useTalk } from '../lib/useTalk';
import RecordButton from '../components/RecordButton';
import ReplyVoice, { useSavedVoices } from '../components/ReplyVoice';
import SaveActions from '../components/SaveActions';
import AddFromDisk from '../components/AddFromDisk';
import { useLibraryVersion } from '../lib/library-changed';

/**
 * Voice to voice, two ways.
 *
 * Talk: speak to a model and hear it answer, hands free. The same loop runs
 * in Chat and Chisel; here it has nothing else around it.
 *
 * Convert: say something in one voice, hear it in another. Chatterbox keeps
 * the words, timing and intonation of the recording and replaces the speaker.
 */

const label = 'text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]';
const field = 'mt-1.5 w-full text-xs px-2.5 py-2 rounded-lg bg-[var(--bg-inset)] outline-none';

type Mode = 'talk' | 'convert';

export default function VoiceToVoice() {
  const [mode, setMode] = useState<Mode>('talk');
  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 flex gap-1">
        {([['talk', 'Talk to a model'], ['convert', 'Convert a recording']] as const).map(([id, text]) => (
          <button key={id} onClick={() => setMode(id)} className={mode === id ? 'pill pill-on' : 'pill'}>
            {id === 'talk' ? <Mic size={14} /> : <Repeat size={14} />}<span>{text}</span>
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0">{mode === 'talk' ? <Talk /> : <Convert />}</div>
    </div>
  );
}

function Talk() {
  const libraryVersion = useLibraryVersion();
  const [models, setModels] = useState<LocalModel[]>([]);
  const [modelPath, setModelPath] = useState('');
  const [voice, setVoice] = useState(() => {
    try { return localStorage.getItem('uncloud.voice.talk') || 'bm_george'; } catch { return 'bm_george'; }
  });
  const [turns, setTurns] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const turnsRef = useRef<ChatMessage[]>([]);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { localStorage.setItem('uncloud.voice.talk', voice); } catch { /* storage refused */ }
  }, [voice]);

  useEffect(() => {
    Promise.all([getLibrary(), engineStatus().catch(() => null)]).then(([ms, status]) => {
      const text = ms.filter((m) => m.category === 'text' && m.ready);
      setModels(text);
      const running = status?.running ? text.find((m) => m.path === status.model_path) : undefined;
      setModelPath((p) => p || running?.path || text[0]?.path || '');
    });
  }, [libraryVersion]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' });
  }, [turns]);

  const talk = useTalk(voice, async (said) => {
    const model = models.find((m) => m.path === modelPath);
    if (!model) return 'Choose a model to talk to first.';
    const history: ChatMessage[] = [...turnsRef.current, { role: 'user', content: said }];
    turnsRef.current = history;
    setTurns(history);
    const status = await engineStatus();
    if (!status.running || status.model_path !== model.path) {
      setLoading(true);
      try { await startEngine(model.path, model.engine); } finally { setLoading(false); }
    }
    let reply = '';
    for await (const chunk of streamChat([
      // Brief: it is read aloud, and lists and markdown do not survive that.
      { role: 'system', content: chatSystemPrompt({ web: false, pictures: false, manner: 'brief' }) },
      ...history,
    ])) {
      if (chunk.kind === 'text') reply += chunk.text;
    }
    const answered: ChatMessage[] = [...history, { role: 'assistant', content: reply.trim() }];
    turnsRef.current = answered;
    setTurns(answered);
    return reply;
  });

  return (
    <div className="h-full flex max-md:flex-col">
      <div className="w-[320px] max-md:w-full shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5">
        <div>
          <label className={label}>Talk to</label>
          {models.length ? (
            <select value={modelPath} onChange={(e) => setModelPath(e.target.value)} className={field} disabled={talk.active}>
              {models.map((m) => <option key={m.path} value={m.path}>{m.name}</option>)}
            </select>
          ) : (
            <div className="mt-1.5 flex flex-col gap-1">
              <p className="text-[11px] text-[var(--text-faint)]">No chat model installed. Download one from Models, or add one you already have.</p>
              <AddFromDisk className="flex items-center gap-1.5 text-[11px] text-[var(--text-dim)] hover:text-white" />
            </div>
          )}
        </div>
        <div>
          <label className={label}>Answers in</label>
          <ReplyVoice value={voice} onChange={setVoice} className={field} />
          <p className="mt-1 text-[10px] text-[var(--text-faint)] leading-relaxed">
            Kokoro answers quickly. Chatterbox and Bark sound richer but take several seconds or
            more per answer. Save more voices in Text to voice.
          </p>
        </div>
        <div>
          <label className={label}>Listening with</label>
          <p className="mt-1.5 text-xs text-[var(--text-dim)]">
            {talk.sttModel ? talk.sttModel.name : 'No speech-to-text model installed. Add Whisper from Models.'}
          </p>
        </div>
        {turns.length > 0 && !talk.active && (
          <button onClick={() => { turnsRef.current = []; setTurns([]); }} className="pill self-start">
            <span>Start a new conversation</span>
          </button>
        )}
      </div>

      <div className="flex-1 min-w-0 flex flex-col">
        <div ref={scroller} className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-3">
          {turns.length === 0 && (
            <div className="m-auto max-w-sm text-center text-sm text-[var(--text-faint)] leading-relaxed">
              Press Talk and speak. It answers aloud, then listens again — no buttons in between.
              Pause for a moment when you have finished a sentence.
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={`max-w-[80%] text-sm leading-relaxed px-3.5 py-2.5 rounded-2xl ${
              t.role === 'user' ? 'self-end bg-[var(--bg-raised)]' : 'self-start bg-[var(--bg-inset)] text-[var(--text-dim)]'}`}>
              {t.content || <Loader2 size={13} className="animate-spin" />}
            </div>
          ))}
        </div>
        <div className="border-t border-[var(--border-soft)] p-5 flex flex-col items-center gap-2">
          <button
            onClick={talk.toggle}
            disabled={!talk.sttModel || !modelPath}
            className={`w-16 h-16 rounded-full flex items-center justify-center transition disabled:opacity-30 ${
              talk.active ? 'btn-accent' : 'bg-[var(--bg-raised)] hover:bg-[var(--bg-inset)]'}`}
            aria-label={talk.active ? 'Stop talking' : 'Talk'}
            title={talk.active ? 'Stop talking' : 'Talk'}
          >
            {talk.active ? <MicOff size={22} /> : <Mic size={22} />}
          </button>
          <span className="text-xs text-[var(--text-dim)]" aria-live="polite">
            {loading ? 'Loading the model…' : talk.active ? describeTalk(talk.state) : 'Talk'}
          </span>
          {talk.error && <p className="text-[11px] text-rose-400 text-center max-w-md">{talk.error}</p>}
        </div>
      </div>
    </div>
  );
}

function Convert() {
  const libraryVersion = useLibraryVersion();
  const [models, setModels] = useState<SpeechModel[]>([]);
  const [installed, setInstalled] = useState(true);
  const [modelPath, setModelPath] = useState('');
  const saved = useSavedVoices().filter((v) => v.engine === 'chatterbox' && v.has_recording);
  const [target, setTarget] = useState('builtin');
  const [source, setSource] = useState<{ path: string; seconds: number } | null>(null);
  const [targetRecording, setTargetRecording] = useState<{ path: string; seconds: number } | null>(null);
  const [busy, setBusy] = useState<'source' | 'target' | null>(null);
  const [job, setJob] = useState<SpeechJob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    speechEngines().then((list) => {
      const chatterbox = list.find((e) => e.id === 'chatterbox');
      const converting = chatterbox?.models.filter((m) => m.converts) ?? [];
      setInstalled(!!chatterbox?.installed);
      setModels(converting);
      setModelPath((p) => p || converting[0]?.path || '');
    }).catch((e) => setError(String(e)));
  }, [libraryVersion]);

  useEffect(() => {
    if (!job || job.finished) return;
    const t = window.setInterval(async () => {
      const next = await speechJob(job.id).catch(() => null);
      if (!next) return;
      setJob(next);
      if (next.status === 'done' && next.clip) setAudioUrl(await speechClipUrl(next.clip.id));
    }, 1000);
    return () => window.clearInterval(t);
  }, [job]);

  async function keep(which: 'source' | 'target', audio: Blob, name?: string) {
    setBusy(which);
    setError(null);
    try {
      const stored = await uploadRecording(audio, name);
      if (which === 'source') setSource(stored); else { setTargetRecording(stored); setTarget('recording'); }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function choose(which: 'source' | 'target') {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'audio/*,.wav,.mp3,.m4a,.flac,.ogg';
    picker.onchange = () => {
      const file = picker.files?.[0];
      if (file) void keep(which, file, file.name);
    };
    picker.click();
  }

  async function convert() {
    if (!modelPath || !source) return;
    setError(null);
    setAudioUrl(null);
    try {
      setJob(await startConversion({
        model_path: modelPath,
        source_path: source.path,
        saved_voice: target.startsWith('saved:') ? target.slice(6) : '',
        recording_path: target === 'recording' ? targetRecording?.path ?? null : null,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const working = !!job && !job.finished;

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="max-w-2xl flex flex-col gap-5">
        {!installed && (
          <p className="text-[11px] text-[var(--text-dim)] card p-3">
            Converting uses Chatterbox, which is not set up yet. Open Text to voice → Chatterbox
            and press Set up.
          </p>
        )}
        {models.length === 0 ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm text-[var(--text-faint)]">
              Converting needs Chatterbox weights that include its voice converter (s3gen). Download
              Chatterbox from Models, or add a folder you already have.
            </p>
            <AddFromDisk className="flex items-center gap-1.5 text-xs text-[var(--text-dim)] hover:text-white" />
          </div>
        ) : models.length > 1 && (
          <div>
            <label className={label}>Model</label>
            <select value={modelPath} onChange={(e) => setModelPath(e.target.value)} className={field}>
              {models.map((m) => <option key={m.path} value={m.path}>{m.name}</option>)}
            </select>
          </div>
        )}

        <section className="card p-4 flex flex-col gap-3">
          <h3 className="text-sm font-medium">1. What to say</h3>
          <div className="flex items-center gap-2 flex-wrap">
            <RecordButton onRecorded={(b) => void keep('source', b)} maxSeconds={120} disabled={busy !== null} />
            <button onClick={() => choose('source')} disabled={busy !== null} className="pill"><Upload size={13} /><span>Choose file</span></button>
            {busy === 'source' && <Loader2 size={13} className="animate-spin text-[var(--text-faint)]" />}
            {source && <span className="text-[11px] text-[var(--text-dim)]">A {source.seconds}s recording</span>}
          </div>
        </section>

        <section className="card p-4 flex flex-col gap-3">
          <h3 className="text-sm font-medium">2. The voice to say it in</h3>
          <select value={target} onChange={(e) => setTarget(e.target.value)} className={field}>
            <option value="builtin">Chatterbox's built-in voice</option>
            {saved.map((v) => <option key={v.slug} value={`saved:${v.slug}`}>{v.name}</option>)}
            <option value="recording">From a recording…</option>
          </select>
          {target === 'recording' && (
            <div className="flex items-center gap-2 flex-wrap">
              <RecordButton onRecorded={(b) => void keep('target', b)} maxSeconds={20} disabled={busy !== null} />
              <button onClick={() => choose('target')} disabled={busy !== null} className="pill"><Upload size={13} /><span>Choose file</span></button>
              {targetRecording && <span className="text-[11px] text-[var(--text-dim)]">A {targetRecording.seconds}s recording</span>}
            </div>
          )}
          <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
            Only convert into a voice that is yours or that you have permission to use. Chatterbox
            marks its output with an inaudible watermark identifying it as generated.
          </p>
        </section>

        <button
          onClick={convert}
          disabled={!installed || !modelPath || !source || working || (target === 'recording' && !targetRecording)}
          className="h-10 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition"
        >
          {working ? <Loader2 size={14} className="animate-spin" /> : <Repeat size={14} />}
          {working ? `${job?.stage || 'Converting'}…` : 'Convert'}
        </button>
        {(error || job?.error) && <p className="text-[11px] text-rose-400 whitespace-pre-wrap">{error || job?.error}</p>}

        {audioUrl && job?.clip && (
          <div className="card p-4 flex flex-col gap-3">
            <p className="text-[11px] text-[var(--text-faint)]">{job.clip.duration.toFixed(1)}s · kept under Clips</p>
            <audio src={audioUrl} controls autoPlay className="w-full h-9" />
            <SaveActions path={job.clip.path} onDiscarded={() => { setAudioUrl(null); setJob(null); }} />
          </div>
        )}
      </div>
    </div>
  );
}
