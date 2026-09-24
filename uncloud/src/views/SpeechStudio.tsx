import ActivityOrb from '../components/ActivityOrb';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AudioLines, BookmarkPlus, Upload, X } from 'lucide-react';
import {
  deleteSavedVoice, installSpeechEngine, saveVoice, speechClipUrl, speechEngines, speechJob,
  speechPresets, startSpeech, uploadRecording,
} from '../lib/sidecar';
import type {
  SavedVoice, SpeechEngine, SpeechJob, SpeechModel, SpeechPreset,
} from '../lib/sidecar';
import Dictate from '../components/Dictate';
import RecordButton from '../components/RecordButton';
import SaveActions from '../components/SaveActions';
import { useSavedVoices } from '../components/ReplyVoice';
import { SplitTabs, useSplit } from '../components/Split';
import { useWhenVisible } from '../components/Panes';
import AddFromDisk from '../components/AddFromDisk';
import { onLibraryChange } from '../lib/library-changed';

/**
 * Text to voice with Kokoro, Chatterbox or Bark.
 *
 * Everything made here is kept — listed under Clips, written to the output
 * folder under a readable name — so a take worth keeping is never one that
 * has to be regenerated because nobody saved it in time.
 */

const WORDS_PER_MINUTE = 150;
const label = 'text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]';
const field = 'mt-1.5 w-full text-xs px-2.5 py-2 rounded-lg bg-[var(--bg-inset)] outline-none';

/** A voice option: a saved voice, an engine preset, or a recording. */
type VoiceChoice =
  | { kind: 'saved'; slug: string }
  | { kind: 'preset'; id: string }
  | { kind: 'recording' };

function encode(choice: VoiceChoice): string {
  return choice.kind === 'saved' ? `saved:${choice.slug}`
    : choice.kind === 'preset' ? `preset:${choice.id}` : 'recording';
}
function decode(value: string): VoiceChoice {
  if (value.startsWith('saved:')) return { kind: 'saved', slug: value.slice(6) };
  if (value.startsWith('preset:')) return { kind: 'preset', id: value.slice(7) };
  return { kind: 'recording' };
}

export default function SpeechStudio({ engineId }: { engineId: string }) {
  const [engines, setEngines] = useState<SpeechEngine[]>([]);
  const engine = engines.find((e) => e.id === engineId) ?? null;
  const [modelPath, setModelPath] = useState('');
  const model: SpeechModel | null = engine?.models.find((m) => m.path === modelPath)
    ?? engine?.models[0] ?? null;
  const [variant, setVariant] = useState('');
  const chosenVariant = model?.variants.find((v) => v.id === variant) ?? model?.variants[0];
  const [language, setLanguage] = useState('en');

  const [presets, setPresets] = useState<SpeechPreset[]>([]);
  const [voiceRefresh, setVoiceRefresh] = useState(0);
  const saved = useSavedVoices(voiceRefresh).filter((v) => v.engine === engineId);
  const [voice, setVoice] = useState('');
  const [recording, setRecording] = useState<{ path: string; seconds: number } | null>(null);
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [controls, setControls] = useState<Record<string, number>>({});

  const [format, setFormat] = useState('wav');
  const [sampleRate, setSampleRate] = useState<number | null>(null);
  const [bitDepth, setBitDepth] = useState(24);

  const [text, setText] = useState('');
  const [job, setJob] = useState<SpeechJob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [naming, setNaming] = useState<string | null>(null);
  const [setting, setSetting] = useState(false);
  const [log, setLog] = useState<string[]>([]);

  const refresh = useCallback(() => {
    speechEngines().then(setEngines).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  // Models downloaded or set up elsewhere appear when this is looked at again.
  useWhenVisible(refresh);
  useEffect(() => onLibraryChange(refresh), [refresh]);

  // A new engine starts from its own defaults, not the last engine's.
  useEffect(() => {
    if (!engine) return;
    setControls(Object.fromEntries(engine.controls.map((c) => [c.id, c.default])));
    setModelPath((p) => (engine.models.some((m) => m.path === p) ? p : engine.models[0]?.path ?? ''));
    setVariant('');
    setRecording(null);
    setVoice('');
    // Only the id matters here; the engine object is re-read on every refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineId, engines.length]);

  useEffect(() => {
    if (!model) { setPresets([]); return; }
    speechPresets(engineId, model.path).then((list) => {
      setPresets(list);
      setVoice((current) => {
        if (current.startsWith('saved:')) return current;
        const english = list.find((p) => /English/.test(p.language)) ?? list[0];
        if (english) return `preset:${english.id}`;
        return engine?.clones ? 'recording' : '';
      });
    }).catch(() => setPresets([]));
  }, [engineId, model?.path, engine?.clones]); // eslint-disable-line react-hooks/exhaustive-deps

  // Choosing a saved voice brings its settings with it.
  const choice = decode(voice);
  const savedChoice: SavedVoice | undefined = choice.kind === 'saved'
    ? saved.find((v) => v.slug === choice.slug) : undefined;
  useEffect(() => {
    if (!savedChoice) return;
    setControls((c) => ({ ...c, ...savedChoice.controls }));
    if (savedChoice.language) setLanguage(savedChoice.language);
    if (savedChoice.variant) setVariant(savedChoice.variant);
  }, [savedChoice?.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!job || job.finished) return;
    const t = window.setInterval(async () => {
      try {
        const next = await speechJob(job.id);
        setJob(next);
        if (next.status === 'done' && next.clip) setAudioUrl(await speechClipUrl(next.clip.id));
      } catch (e) {
        setError(String(e));
      }
    }, 1000);
    return () => window.clearInterval(t);
  }, [job]);

  const languages = chosenVariant?.languages ?? [];
  const multilingual = engineId === 'chatterbox' && languages.length > 1;

  async function takeRecording(audio: Blob, name?: string) {
    setRecordingBusy(true);
    setError(null);
    try {
      setRecording(await uploadRecording(audio, name));
      setVoice('recording');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRecordingBusy(false);
    }
  }

  function chooseFile() {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'audio/*,.wav,.mp3,.m4a,.flac,.ogg';
    picker.onchange = () => {
      const file = picker.files?.[0];
      if (file) void takeRecording(file, file.name);
    };
    picker.click();
  }

  async function setUp() {
    setSetting(true);
    setLog([]);
    setError(null);
    try {
      for await (const event of installSpeechEngine(engineId)) {
        if (event.line) setLog((l) => [...l, event.line!].slice(-200));
        if (event.error) setError(event.error);
      }
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSetting(false);
    }
  }

  async function generate() {
    if (!engine || !model || !text.trim()) return;
    setError(null);
    setAudioUrl(null);
    try {
      setJob(await startSpeech({
        text,
        engine: engineId,
        model_path: model.path,
        variant: chosenVariant?.id ?? '',
        language: multilingual ? language : '',
        voice: choice.kind === 'preset' ? choice.id : '',
        saved_voice: choice.kind === 'saved' ? choice.slug : '',
        recording_path: choice.kind === 'recording' ? recording?.path ?? null : null,
        controls,
        format,
        sample_rate: sampleRate,
        bit_depth: bitDepth,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function keepVoice() {
    if (!engine || !model || !naming?.trim()) return;
    setError(null);
    try {
      const kept = await saveVoice({
        name: naming.trim(),
        engine: engineId,
        model_path: model.path,
        variant: chosenVariant?.id ?? '',
        preset: choice.kind === 'preset' ? choice.id : savedChoice?.preset ?? '',
        language: multilingual ? language : '',
        controls,
        recording_path: choice.kind === 'recording' ? recording?.path ?? null
          : savedChoice?.reference ?? null,
      });
      setNaming(null);
      setVoiceRefresh((n) => n + 1);
      setVoice(`saved:${kept.slug}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function forgetVoice() {
    if (!savedChoice) return;
    try {
      await deleteSavedVoice(savedChoice.slug);
      setVoiceRefresh((n) => n + 1);
      setVoice(presets[0] ? `preset:${presets[0].id}` : engine?.clones ? 'recording' : '');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const words = useMemo(() => (text.trim() ? text.trim().split(/\s+/).length : 0), [text]);
  const busy = !!job && !job.finished;
  const split = useSplit(busy);
  const needsRecording = choice.kind === 'recording' && !recording;
  const canGenerate = !!engine?.installed && !!model && !!text.trim() && !busy
    && !needsRecording && !!voice;

  if (!engine) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-[var(--text-faint)]">
        {error ?? <ActivityOrb state="working" size={20} label="Working…" />}
      </div>
    );
  }

  return (
    <div className="h-full flex split">
      <SplitTabs split={split} labels={['Voice', 'Script']} />
      <div className={`w-[320px] shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5 split-pane${split.on(0)}`}>
        <p className="text-[11px] text-[var(--text-dim)] leading-relaxed">{engine.summary}</p>

        {!engine.installed && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-inset)] p-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-[var(--text-dim)]">{engine.label} is not set up yet</span>
              <button onClick={setUp} disabled={setting}
                      className="text-[11px] px-2.5 py-1 rounded-md btn-accent disabled:opacity-40">
                {setting ? 'Setting up…' : 'Set up'}
              </button>
            </div>
            <p className="mt-1 text-[10px] text-[var(--text-faint)] leading-relaxed">
              It runs in its own environment, because it needs older library versions than
              the rest of Uncloud. About 2 GB, once, and this step needs the internet.
            </p>
            {setting && log.length > 0 && (
              <pre className="mt-2 max-h-32 overflow-y-auto text-[10px] font-mono text-[var(--text-faint)] whitespace-pre-wrap">
                {log.slice(-40).join('\n')}
              </pre>
            )}
          </div>
        )}

        <div>
          <label className={label}>Model</label>
          {engine.models.length ? (
            <select value={model?.path ?? ''} onChange={(e) => setModelPath(e.target.value)} className={field}>
              {engine.models.map((m) => <option key={m.path} value={m.path}>{m.name}</option>)}
            </select>
          ) : (
            <div className="mt-1.5 flex flex-col gap-1">
              <p className="text-[11px] text-[var(--text-faint)] leading-relaxed">
                No {engine.label} weights found. Download them from Models, or add a folder you
                already have.
              </p>
              <AddFromDisk className="flex items-center gap-1.5 text-[11px] text-[var(--text-dim)] hover:text-white" />
            </div>
          )}
        </div>

        {model && model.variants.length > 1 && (
          <div>
            <label className={label}>Weights</label>
            <select value={chosenVariant?.id ?? ''} onChange={(e) => setVariant(e.target.value)} className={field}>
              {model.variants.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </div>
        )}

        {multilingual && (
          <div>
            <label className={label}>Language</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className={field}>
              {languages.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </div>
        )}

        {model && (
          <div>
            <div className="flex items-center justify-between">
              <label className={label}>Voice</label>
              {savedChoice ? (
                <button onClick={forgetVoice} className="text-[10px] text-[var(--text-faint)] hover:text-rose-400">
                  Forget this voice
                </button>
              ) : (
                <button onClick={() => setNaming('')} disabled={needsRecording || !voice}
                        className="flex items-center gap-1 text-[10px] text-[var(--text-faint)] hover:text-[var(--text-dim)] disabled:opacity-40">
                  <BookmarkPlus size={11} /> Save this voice
                </button>
              )}
            </div>
            <select value={voice} onChange={(e) => setVoice(e.target.value)} className={field}>
              {saved.length > 0 && (
                <optgroup label="Your voices">
                  {saved.map((v) => <option key={v.slug} value={encode({ kind: 'saved', slug: v.slug })}>{v.name}</option>)}
                </optgroup>
              )}
              {presets.length > 0 && (
                <optgroup label={`${engine.label} voices`}>
                  {presets.map((p) => (
                    <option key={p.id} value={encode({ kind: 'preset', id: p.id })}>
                      {p.name}{p.language ? ` — ${p.language}` : ''}{p.notes ? `, ${p.notes}` : ''}
                    </option>
                  ))}
                </optgroup>
              )}
              {engine.clones && <option value="recording">From a recording…</option>}
            </select>

            {naming !== null && (
              <div className="mt-2 flex gap-1.5">
                <input autoFocus value={naming} onChange={(e) => setNaming(e.target.value)}
                       onKeyDown={(e) => { if (e.key === 'Enter') void keepVoice(); if (e.key === 'Escape') setNaming(null); }}
                       placeholder="Name this voice"
                       className="flex-1 min-w-0 text-xs px-2.5 py-1.5 rounded-lg bg-[var(--bg-inset)] outline-none" />
                <button onClick={keepVoice} disabled={!naming.trim()} className="text-[11px] px-2.5 rounded-md btn-accent disabled:opacity-40">Save</button>
                <button onClick={() => setNaming(null)} aria-label="Cancel" className="px-1.5 text-[var(--text-faint)]"><X size={13} /></button>
              </div>
            )}
            {naming !== null && (
              <p className="mt-1 text-[10px] text-[var(--text-faint)] leading-relaxed">
                Keeps the voice and these settings. It appears in Chat, Chisel and Voice to voice.
              </p>
            )}

            {choice.kind === 'recording' && (
              <div className="mt-2 flex flex-col gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <RecordButton onRecorded={(b) => void takeRecording(b)} maxSeconds={20} disabled={recordingBusy} />
                  <button type="button" onClick={chooseFile} disabled={recordingBusy} className="pill">
                    <Upload size={13} /> <span>Choose file</span>
                  </button>
                  {recordingBusy && <ActivityOrb state="working" size={20} label="Working…" />}
                </div>
                <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
                  {recording ? `Using a ${recording.seconds}s recording. ` : ''}
                  Ten seconds of clear speech, with no music behind it, works best. Only use a
                  voice that is yours or that you have permission to use.
                </p>
              </div>
            )}
          </div>
        )}

        {engine.controls.map((c) => (
          <div key={c.id}>
            <div className="flex items-center justify-between">
              <label className={label}>{c.label}</label>
              <span className="text-[10px] text-[var(--text-faint)] tabular-nums">{(controls[c.id] ?? c.default).toFixed(2)}</span>
            </div>
            <input type="range" min={c.min} max={c.max} step={c.step}
                   value={controls[c.id] ?? c.default}
                   onChange={(e) => setControls((v) => ({ ...v, [c.id]: Number(e.target.value) }))}
                   className="mt-1.5 w-full" />
            {c.hint && <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">{c.hint}</p>}
          </div>
        ))}

        <div className="grid grid-cols-3 gap-2">
          <label className="flex flex-col gap-1.5">
            <span className={label}>Format</span>
            <select value={format} onChange={(e) => setFormat(e.target.value)} className="bg-[var(--bg-inset)] rounded-lg px-2 py-2 text-xs outline-none">
              {['wav', 'flac', 'aiff'].map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className={label}>Rate</span>
            <select value={sampleRate ?? ''} onChange={(e) => setSampleRate(e.target.value ? Number(e.target.value) : null)}
                    className="bg-[var(--bg-inset)] rounded-lg px-2 py-2 text-xs outline-none">
              <option value="">Native</option>
              {[44100, 48000].map((r) => <option key={r} value={r}>{(r / 1000).toFixed(1)}k</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className={label}>Depth</span>
            <select value={bitDepth} onChange={(e) => setBitDepth(Number(e.target.value))} className="bg-[var(--bg-inset)] rounded-lg px-2 py-2 text-xs outline-none">
              {[16, 24, 32].map((b) => <option key={b} value={b}>{b}-bit</option>)}
            </select>
          </label>
        </div>

        <button onClick={generate} disabled={!canGenerate}
                className="h-10 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition">
          {busy ? <ActivityOrb state="working" size={20} label="Working…" /> : <AudioLines size={14} />}
          {busy ? (job?.total ? `Speaking ${job.done} of ${job.total}…` : `${job?.stage || 'Starting'}…`) : 'Speak'}
        </button>
        {error && <p className="text-[11px] text-rose-400 whitespace-pre-wrap">{error}</p>}
      </div>

      <div className={`flex-1 min-w-0 flex flex-col split-pane${split.on(1)}`}>
        <div className="flex-1 p-6 flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-2">
            <label className={label}>Script</label>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[var(--text-faint)] tabular-nums">
                {words.toLocaleString()} words · ≈{words / WORDS_PER_MINUTE < 1 ? '<1' : (words / WORDS_PER_MINUTE).toFixed(0)} min
              </span>
              <Dictate title="Dictate the script" onText={(t) => setText((v) => (v ? v.trimEnd() + ' ' + t : t))} />
            </div>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Type or paste what to say. Long scripts are fine — they are spoken a few sentences at a time and joined."
            className="flex-1 min-h-0 bg-[var(--bg-inset)] rounded-lg px-3 py-3 text-sm outline-none resize-none leading-relaxed placeholder:text-[var(--text-faint)]"
          />
        </div>

        {(audioUrl || busy || job?.status === 'error') && (
          <div className="border-t border-[var(--border-soft)] p-4">
            {audioUrl && job?.clip ? (
              <div className="card p-4 flex flex-col gap-3">
                <div>
                  <h3 className="text-sm font-medium truncate">{job.clip.name}</h3>
                  <p className="text-[10px] text-[var(--text-faint)] mt-0.5">
                    {job.clip.duration.toFixed(1)}s · {engine.label} · {job.clip.voice} · kept under Clips
                  </p>
                </div>
                <audio src={audioUrl} controls autoPlay className="w-full h-9" />
                <SaveActions path={job.clip.path} onDiscarded={() => { setAudioUrl(null); setJob(null); }} />
              </div>
            ) : job?.status === 'error' ? (
              <div className="text-sm text-rose-400 whitespace-pre-wrap">{job.error}</div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-[var(--text-dim)]">
                <ActivityOrb state="working" size={20} label="Working…" />
                {job?.total ? `Speaking part ${job.done} of ${job.total}` : job?.stage || 'Starting'}
                {engineId !== 'kokoro' && ' — the first run loads the model, which takes a little while.'}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
