import { useEffect, useRef, useState } from 'react';
import { Loader2, Music, Download, Layers, ChevronDown } from 'lucide-react';
import {
  getMusicOptions, generateMusic, getMusicJob, musicAudioUrl, getLibrary,
} from '../lib/sidecar';
import type { MusicOptions, MusicJob, LocalModel } from '../lib/sidecar';

type Mode = 'song' | 'instrumental';

export default function MusicView() {
  const [options, setOptions] = useState<MusicOptions | null>(null);
  const [models, setModels] = useState<LocalModel[]>([]);
  const [model, setModel] = useState<LocalModel | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const [mode, setMode] = useState<Mode>('instrumental');
  const [prompt, setPrompt] = useState('');
  const [lyrics, setLyrics] = useState('');
  const [duration, setDuration] = useState(180);
  const [bpm, setBpm] = useState('');
  const [keyscale, setKeyscale] = useState('');
  const [sampleRate, setSampleRate] = useState(44100);
  const [bitDepth, setBitDepth] = useState(24);
  const [wantStems, setWantStems] = useState(false);

  const [job, setJob] = useState<MusicJob | null>(null);
  const [mixUrl, setMixUrl] = useState<string | null>(null);
  const [stemUrls, setStemUrls] = useState<Record<string, string>>({});
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    getMusicOptions().then(setOptions).catch(() => setOptions(null));
    getLibrary().then((list) => {
      // ACE-Step ships as a folder of sub-models rather than a single file.
      const music = list.filter((m) => m.category === 'music' || /ace-?step/i.test(m.name));
      setModels(music);
      setModel((p) => p ?? music[0] ?? null);
    });
  }, []);

  useEffect(() => {
    if (!job || job.done) return;
    const t = window.setInterval(async () => {
      const updated = await getMusicJob(job.id);
      setJob(updated);
      if (updated.done && updated.status === 'done') {
        setMixUrl(await musicAudioUrl(updated.id).catch(() => null));
        const urls: Record<string, string> = {};
        for (const name of Object.keys(updated.stems || {})) {
          const u = await musicAudioUrl(updated.id, name).catch(() => null);
          if (u) urls[name] = u;
        }
        setStemUrls(urls);
      }
    }, 2000);
    pollRef.current = t;
    return () => window.clearInterval(t);
  }, [job]);

  async function run() {
    if (!model || !prompt.trim() || (job && !job.done)) return;
    setMixUrl(null);
    setStemUrls({});
    setJob(await generateMusic({
      model_dir: model.path,
      prompt: prompt.trim(),
      lyrics: mode === 'song' ? lyrics : '',
      instrumental: mode === 'instrumental',
      duration,
      bpm: bpm ? Number(bpm) : null,
      keyscale,
      sample_rate: sampleRate,
      bit_depth: bitDepth,
      separate_stems: wantStems,
    }));
  }

  function download(url: string, name: string) {
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
  }

  const busy = !!job && !job.done;
  const mins = Math.floor(duration / 60);
  const secs = duration % 60;

  return (
    <div className="h-full flex">
      <div className="w-[340px] shrink-0 border-r border-[var(--border-soft)] overflow-y-auto p-4 flex flex-col gap-5">
        {/* model */}
        <div className="relative">
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Model</label>
          <button
            onClick={() => setPickerOpen((v) => !v)}
            className="mt-1.5 w-full flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-[var(--bg-inset)] hover:bg-[var(--bg-inset)]/70 transition"
          >
            <span className={model ? '' : 'text-[var(--text-faint)]'}>
              {model ? model.name : 'No music model installed'}
            </span>
            <ChevronDown size={13} className="text-[var(--text-faint)]" />
          </button>
          {pickerOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 card p-1.5 z-20 shadow-2xl">
              {models.length === 0 && (
                <div className="text-[11px] text-[var(--text-faint)] px-2 py-3 text-center">
                  Install ACE-Step from the Models tab.
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
          {options && !options.installed && (
            <p className="mt-1.5 text-[10px] text-amber-400/90">
              ACE-Step runtime not installed — see Settings.
            </p>
          )}
        </div>

        {/* song vs instrumental */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Type</label>
          <div className="mt-1.5 flex gap-1 bg-[var(--bg-inset)] p-1 rounded-lg">
            {(['instrumental', 'song'] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 text-xs py-1.5 rounded-md transition ${
                  mode === m ? 'bg-[var(--bg-raised)] text-white' : 'text-[var(--text-faint)] hover:text-[var(--text-dim)]'
                }`}
              >
                {m === 'instrumental' ? 'Instrumental' : 'With vocals'}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Style</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="e.g. warm lo-fi hip hop, mellow rhodes piano, soft vinyl crackle"
            className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none resize-none placeholder:text-[var(--text-faint)]"
          />
        </div>

        {mode === 'song' && (
          <div>
            <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Lyrics</label>
            <textarea
              value={lyrics}
              onChange={(e) => setLyrics(e.target.value)}
              rows={6}
              placeholder={'[verse]\nyour words here\n\n[chorus]\n…'}
              className="mt-1.5 w-full bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none resize-none font-mono placeholder:text-[var(--text-faint)]"
            />
          </div>
        )}

        <div>
          <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">
            Length — {mins}:{String(secs).padStart(2, '0')}
          </label>
          <input
            type="range" min={30} max={options?.max_duration ?? 600} step={15}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="mt-2 w-full"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">BPM</span>
            <input
              value={bpm} onChange={(e) => setBpm(e.target.value.replace(/\D/g, ''))}
              placeholder="auto"
              className="bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none placeholder:text-[var(--text-faint)]"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Key</span>
            <input
              value={keyscale} onChange={(e) => setKeyscale(e.target.value)}
              placeholder="e.g. C minor"
              className="bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none placeholder:text-[var(--text-faint)]"
            />
          </label>
        </div>

        {/* export format — matters for Logic */}
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Sample rate</span>
            <select
              value={sampleRate} onChange={(e) => setSampleRate(Number(e.target.value))}
              className="bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none"
            >
              {(options?.sample_rates ?? [44100]).map((r) => (
                <option key={r} value={r}>{(r / 1000).toFixed(1)} kHz</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">Bit depth</span>
            <select
              value={bitDepth} onChange={(e) => setBitDepth(Number(e.target.value))}
              className="bg-[var(--bg-inset)] rounded-lg px-2.5 py-2 text-xs outline-none"
            >
              {(options?.bit_depths ?? [24]).map((b) => (
                <option key={b} value={b}>{b}-bit</option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex items-center gap-2 text-xs text-[var(--text-dim)] cursor-pointer select-none">
          <input type="checkbox" checked={wantStems} onChange={(e) => setWantStems(e.target.checked)} />
          <Layers size={13} /> Split into stems
        </label>

        <button
          onClick={run}
          disabled={!model || !prompt.trim() || busy}
          className="h-10 rounded-xl bg-white text-black text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-30 disabled:bg-[var(--border)] disabled:text-[var(--text-faint)] transition"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Music size={14} />}
          {busy ? (job?.stage || 'Working…') : 'Generate'}
        </button>
      </div>

      {/* result */}
      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        {mixUrl ? (
          <div className="max-w-xl flex flex-col gap-5">
            <div className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium">Mixdown</h3>
                <button
                  onClick={() => download(mixUrl, `uncloud-${job?.id}.wav`)}
                  className="flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition"
                >
                  <Download size={12} /> WAV
                </button>
              </div>
              <audio src={mixUrl} controls className="w-full h-9" />
              <p className="mt-2 text-[10px] text-[var(--text-faint)]">
                {(sampleRate / 1000).toFixed(1)} kHz · {bitDepth}-bit · ready to drop into Logic
              </p>
            </div>

            {Object.keys(stemUrls).length > 0 && (
              <div className="card p-4">
                <h3 className="text-sm font-medium mb-3">Stems</h3>
                <div className="flex flex-col gap-3">
                  {Object.entries(stemUrls).map(([name, url]) => (
                    <div key={name}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs capitalize">{name}</span>
                        <button
                          onClick={() => download(url, `uncloud-${job?.id}-${name}.wav`)}
                          className="text-[var(--text-faint)] hover:text-white transition"
                        >
                          <Download size={12} />
                        </button>
                      </div>
                      <audio src={url} controls className="w-full h-8" />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : busy ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 text-[var(--text-dim)]">
            <Loader2 size={22} className="animate-spin" />
            <span className="text-sm">{job?.stage || 'Working…'}</span>
            <span className="text-[11px] text-[var(--text-faint)]">
              First run loads ~10GB — later runs are quicker.
            </span>
          </div>
        ) : job?.status === 'error' ? (
          <div className="text-sm text-rose-400 max-w-lg whitespace-pre-wrap">{job.error}</div>
        ) : (
          <div className="h-full flex items-center justify-center text-sm text-[var(--text-faint)]">
            Describe a style and generate.
          </div>
        )}
      </div>
    </div>
  );
}
