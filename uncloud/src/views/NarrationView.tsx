import { useEffect, useState } from 'react';
import { Loader2, Mic2, Download, ChevronDown } from 'lucide-react';
import {
  getNarrationOptions, generateNarration, getNarrationJob, narrationAudioUrl, getLibrary,
} from '../lib/sidecar';
import type { NarrationOptions, NarrationJob, LocalModel } from '../lib/sidecar';

/** Rough reading pace, for estimating output length before generating. */
const WORDS_PER_MINUTE = 150;

export default function NarrationView() {
  const [options, setOptions] = useState<NarrationOptions | null>(null);
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const [text, setText] = useState('');
  const [voice, setVoice] = useState('');
  const [quality, setQuality] = useState('balanced');
  const [engine, setEngine] = useState('realtime');
  const [sampleRate, setSampleRate] = useState(44100);
  const [bitDepth, setBitDepth] = useState(24);
  const [format, setFormat] = useState('wav');

  const [job, setJob] = useState<NarrationJob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  useEffect(() => {
    getNarrationOptions(engine).then((o) => {
      setOptions(o);
      const english = o.voices.find((v) => v.notes.startsWith('English'));
      // voices differ per engine, so re-pick when switching
      setVoice(english?.slug || o.voices[0]?.slug || '');
    }).catch(() => setOptions(null));

    getLibrary().then((list) => {
      const tts = list.filter((m) => /vibevoice/i.test(m.name) || m.category === 'voice-tts');
      setModels(tts);
      setModel((p) => p ?? tts[0] ?? null);
    });
  }, [engine]);

  useEffect(() => {
    if (!job || job.done) return;
    const t = window.setInterval(async () => {
      const updated = await getNarrationJob(job.id);
      setJob(updated);
      if (updated.done && updated.status === 'done') {
        setAudioUrl(await narrationAudioUrl(updated.id).catch(() => null));
      }
    }, 2000);
    return () => window.clearInterval(t);
  }, [job]);

  async function run() {
    if (!model || !text.trim() || (job && !job.done)) return;
    setAudioUrl(null);
    setJob(await generateNarration({
      model_dir: model.path,
      text: text.trim(),
      voice_slug: voice,
      sample_rate: sampleRate,
      bit_depth: bitDepth,
      audio_format: format,
      ddpm_steps: options?.quality[quality] ?? 20,
      engine,
    }));
  }

  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estMin = words / WORDS_PER_MINUTE;
  const busy = !!job && !job.done;

  return (
    <div className="h-full flex">
      <div className="w-[320px] shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5">
        <div className="relative">
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Model</label>
          <button
            onClick={() => setPickerOpen((v) => !v)}
            className="mt-1.5 w-full flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-[var(--bg-inset)] hover:bg-[var(--bg-inset)]/70 transition"
          >
            <span className={model ? '' : 'text-[var(--text-faint)]'}>
              {model ? model.name : 'No narration model installed'}
            </span>
            <ChevronDown size={13} className="text-[var(--text-faint)]" />
          </button>
          {pickerOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 card p-1.5 z-20 shadow-2xl">
              {models.length === 0 && (
                <div className="text-[11px] text-[var(--text-faint)] px-2 py-3 text-center">
                  Install VibeVoice from the Models tab.
                </div>
              )}
              {models.map((m) => (
                <button
                  key={m.id}
                  onClick={() => { setModel(m); setPickerOpen(false); }}
                  className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-[var(--bg-inset)] transition text-xs"
                >
                  {m.name}
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Engine</label>
          <div className="mt-1.5 flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg">
            {(options?.engines ?? []).map((e) => (
              <button
                key={e.id}
                onClick={() => setEngine(e.id)}
                disabled={!e.installed}
                title={e.note}
                className={`flex-1 text-[11px] py-1.5 rounded-md transition disabled:opacity-30 ${
                  engine === e.id ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                {e.label}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-[var(--text-faint)]">
            {options?.engines?.find((e) => e.id === engine)?.note}
          </p>
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">
            Voice {options && <span className="text-[var(--text-faint)]">({options.voices.length})</span>}
          </label>
          <select
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none"
          >
            {(options?.voices ?? []).map((v) => (
              <option key={v.slug} value={v.slug}>
                {v.name} — {v.notes}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Quality</label>
          <div className="mt-1.5 flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg">
            {Object.keys(options?.quality ?? { balanced: 20 }).map((q) => (
              <button
                key={q}
                onClick={() => setQuality(q)}
                className={`flex-1 text-[11px] py-1.5 rounded-md capitalize transition ${
                  quality === q ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                {q}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-[var(--text-faint)]">
            {options?.quality[quality] ?? 20} diffusion steps — higher is clearer but slower.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Format</span>
            <select
              value={format} onChange={(e) => setFormat(e.target.value)}
              className="bg-[var(--bg-inset)] rounded-lg px-2 py-2 text-xs outline-none"
            >
              {(options?.formats ?? ['wav']).map((f) => (
                <option key={f} value={f}>{f.toUpperCase()}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Rate</span>
            <select
              value={sampleRate} onChange={(e) => setSampleRate(Number(e.target.value))}
              className="bg-[var(--bg-inset)] rounded-lg px-2 py-2 text-xs outline-none"
            >
              {(options?.sample_rates ?? [44100]).map((r) => (
                <option key={r} value={r}>{(r / 1000).toFixed(1)}k</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Depth</span>
            <select
              value={bitDepth} onChange={(e) => setBitDepth(Number(e.target.value))}
              className="bg-[var(--bg-inset)] rounded-lg px-2 py-2 text-xs outline-none"
            >
              {(options?.bit_depths ?? [24]).map((b) => (
                <option key={b} value={b}>{b}-bit</option>
              ))}
            </select>
          </label>
        </div>

        <button
          onClick={run}
          disabled={!model || !text.trim() || busy}
          className="h-10 rounded-xl btn-accent text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 transition"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Mic2 size={14} />}
          {busy ? (job?.stage || 'Narrating…') : 'Narrate'}
        </button>
      </div>

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 p-6 flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-2">
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Script</label>
            <span className="text-[10px] text-[var(--text-faint)] tabular-nums">
              {words.toLocaleString()} words · ≈{estMin < 1 ? '<1' : estMin.toFixed(0)} min
            </span>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste your script. Long-form is fine — this generates in one pass, so the voice stays consistent throughout."
            className="flex-1 min-h-0 bg-[var(--bg-inset)] rounded-lg px-3 py-3 text-sm outline-none resize-none leading-relaxed placeholder:text-[var(--text-faint)]"
          />
        </div>

        {(audioUrl || busy || job?.status === 'error') && (
          <div className="border-t border-[var(--border-soft)] p-4">
            {audioUrl ? (
              <div className="card p-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h3 className="text-sm font-medium">Narration</h3>
                    <p className="text-[10px] text-[var(--text-faint)] mt-0.5">
                      {job?.duration_s}s · {(sampleRate / 1000).toFixed(1)} kHz · {bitDepth}-bit {format.toUpperCase()}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      const a = document.createElement('a');
                      a.href = audioUrl;
                      a.download = `uncloud-narration-${job?.id}.${format}`;
                      a.click();
                    }}
                    className="flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition"
                  >
                    <Download size={12} /> Save
                  </button>
                </div>
                <audio src={audioUrl} controls className="w-full h-9" />
              </div>
            ) : job?.status === 'error' ? (
              <div className="text-sm text-rose-400 whitespace-pre-wrap">{job.error}</div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-[var(--text-dim)]">
                <Loader2 size={14} className="animate-spin" /> {job?.stage || 'Narrating…'}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
