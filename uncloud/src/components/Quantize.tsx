import { useEffect, useState } from 'react';
import { Gauge, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import {
  getQuantizeBases, startQuantize, listQuantizeJobs,
} from '../lib/sidecar';
import type { LocalModel, QuantizeBase, QuantizeJob } from '../lib/sidecar';

/**
 * Build a pre-quantised MLX copy of a model, choosing precision per component.
 *
 * The two halves do not deserve the same budget. The transformer decides every
 * pixel — faces first, because fine facial structure is the highest-frequency
 * detail in an image and the first thing coarse weights ruin. The text encoder
 * only turns a prompt into a direction, and carries that fine at low precision.
 *
 * Lower precision is not faster here: on Apple Silicon a bf16 matmul measured
 * 13.6 TFLOPS against 11.9 for int4. It buys memory, not speed, so the right
 * choice is the highest precision that still fits.
 */

// What a model of this size costs to hold, roughly, per bit width.
function estimate(model: LocalModel, tBits: number, eBits: number): string {
  if (!model.size_gb) return '';
  // Source is bf16 (16 bits); the two halves are close to even in these models.
  const half = model.size_gb / 2;
  const gb = (half * tBits) / 16 + (half * eBits) / 16;
  return `~${gb.toFixed(1)} GB`;
}

function guessBase(name: string, bases: QuantizeBase[]): string {
  const n = name.toLowerCase();
  const has = (id: string) => bases.some((b) => b.id === id);
  if (n.includes('klein')) {
    if (n.includes('4b') && has('flux2_klein_4b')) return 'flux2_klein_4b';
    if (has('flux2_klein_9b')) return 'flux2_klein_9b';
  }
  if (n.includes('krea') && has('krea2')) return 'krea2';
  if (n.includes('z-image') || n.includes('z image')) return 'z_image_turbo';
  if (n.includes('kontext') && has('dev_kontext')) return 'dev_kontext';
  return bases[0]?.id ?? '';
}

export default function Quantize({ models, onBuilt }: {
  models: LocalModel[];
  onBuilt: () => void;
}) {
  const [bases, setBases] = useState<QuantizeBase[]>([]);
  const [bits, setBits] = useState<number[]>([4, 6, 8]);
  const [jobs, setJobs] = useState<QuantizeJob[]>([]);

  const [source, setSource] = useState<string>('');
  const [base, setBase] = useState<string>('');
  const [tBits, setTBits] = useState(8);
  const [eBits, setEBits] = useState(4);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Anything already stored as MLX shards is done; offering to requantise it
  // would just be a lossy copy of a lossy copy.
  const candidates = models.filter(
    (m) => m.category === 'image' && !m.mflux_base && m.size_gb > 1,
  );

  useEffect(() => {
    getQuantizeBases()
      .then((r) => { setBases(r.bases); setBits(r.bits); })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const read = () => listQuantizeJobs().then(setJobs).catch(() => undefined);
    read();
    const t = setInterval(read, 2000);
    return () => clearInterval(t);
  }, []);

  // A finished build changes the library, so tell the page above.
  useEffect(() => {
    if (jobs.some((j) => j.status === 'done')) onBuilt();
  }, [jobs.filter((j) => j.status === 'done').length]);

  const model = candidates.find((m) => m.path === source) ?? null;

  useEffect(() => {
    if (!model || !bases.length) return;
    setBase(guessBase(model.name, bases));
    setName(`${model.name} (${tBits === eBits ? `${tBits}-bit` : `${tBits}/${eBits}-bit`} MLX)`);
  }, [source, bases.length, tBits, eBits]);

  async function build() {
    if (!model || !base || !name.trim()) return;
    setError(null);
    try {
      await startQuantize({
        source: model.path, base, name: name.trim(),
        transformer_bits: tBits, encoder_bits: eBits,
      });
      setJobs(await listQuantizeJobs().catch(() => []));
    } catch (e) {
      setError(String(e));
    }
  }

  if (!candidates.length) return null;
  const running = jobs.filter((j) => !j.done);
  const select = 'bg-[var(--bg-inset)] text-xs px-2 py-1.5 rounded-lg border border-[var(--border-soft)]';

  return (
    <section className="card p-4 mb-8">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-8 h-8 rounded-lg bg-[var(--bg-inset)] flex items-center justify-center shrink-0">
          <Gauge size={15} className="text-[var(--text-dim)]" />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm mb-1">Make a version that fits this Mac</h2>
          <p className="text-[11px] text-[var(--text-faint)] max-w-2xl leading-relaxed">
            Quantises a model once and saves the result, so it loads in seconds and
            stays in memory instead of being rebuilt for every prompt. Precision is
            per component: the transformer decides every pixel and faces suffer
            first when it is coarse, while the text encoder only turns your prompt
            into a direction and carries that fine at 4-bit. Lower precision buys
            memory, not speed — pick the highest that fits.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Model</span>
          <select className={`${select} w-64`} value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">Choose a model…</option>
            {candidates.map((m) => (
              <option key={m.id} value={m.path}>{m.name} · {m.size_gb} GB</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Based on</span>
          <select className={`${select} w-52`} value={base} onChange={(e) => setBase(e.target.value)}>
            {bases.map((b) => <option key={b.id} value={b.id}>{b.cli}</option>)}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Detail</span>
          <select className={select} value={tBits} onChange={(e) => setTBits(Number(e.target.value))}>
            {bits.map((b) => <option key={b} value={b}>{b}-bit</option>)}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Prompt</span>
          <select className={select} value={eBits} onChange={(e) => setEBits(Number(e.target.value))}>
            {bits.map((b) => <option key={b} value={b}>{b}-bit</option>)}
          </select>
        </label>

        <label className="flex flex-col gap-1 flex-1 min-w-48">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Save as</span>
          <input className={`${select} w-full`} value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="Name for the new model" />
        </label>

        <button
          onClick={build}
          disabled={!model || !base || !name.trim()}
          className="btn-accent text-xs px-4 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Build
        </button>
      </div>

      {model && (
        <p className="text-[11px] text-[var(--text-faint)] mt-2">
          {model.size_gb} GB → {estimate(model, tBits, eBits)} ·{' '}
          {tBits === eBits ? 'one pass' : 'two passes, one per precision'} · a few
          minutes, and the machine will be busy.
        </p>
      )}

      {error && <p className="text-[11px] text-rose-400 mt-2">{error}</p>}

      {(running.length > 0 || jobs.length > 0) && (
        <div className="mt-4 flex flex-col gap-2">
          {jobs.slice(-4).map((j) => (
            <div key={j.id} className="bg-[var(--bg-inset)] rounded-lg px-3 py-2">
              <div className="flex items-center gap-2 text-xs">
                {j.status === 'running' && <Loader2 size={13} className="animate-spin text-[var(--text-dim)]" />}
                {j.status === 'done' && <CheckCircle2 size={13} className="text-emerald-400" />}
                {j.status === 'error' && <XCircle size={13} className="text-rose-400" />}
                <span className="truncate">{j.name}</span>
                <span className="text-[var(--text-faint)] ml-auto shrink-0">
                  {j.status === 'done' ? `${j.size_gb} GB` : j.stage}
                </span>
              </div>
              {j.error && <p className="text-[11px] text-rose-400 mt-1">{j.error}</p>}
              {j.status === 'running' && j.log.length > 0 && (
                <p className="text-[10px] font-mono text-[var(--text-faint)] mt-1 truncate">
                  {j.log[j.log.length - 1]}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
