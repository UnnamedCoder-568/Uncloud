import { useEffect, useState } from 'react';
import { Gauge, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import {
  getQuantizeBases, startQuantize, listQuantizeJobs,
} from '../lib/sidecar';
import type { LocalModel, QuantizeBase, QuantizeJob } from '../lib/sidecar';

/**
 * Build a pre-quantised MLX copy of a model at one precision.
 *
 * There used to be two controls here — a high-precision transformer beside a
 * cheap text encoder, which is the trade anyone would want. It could not work:
 * mflux reads a single precision per checkpoint and applies it to every
 * component, so the mixed build's encoder was read at the wrong width and
 * returned nonsense. Uniform 6-bit costs what 8/4 was meant to cost.
 *
 * Lower precision is not faster here: on Apple Silicon a bf16 matmul measured
 * 13.6 TFLOPS against 11.9 for int4. It buys memory, not speed, so the right
 * choice is the highest precision that still fits.
 */

/** Models this can actually work on.
 *
 *  Exported because the screen around it has to answer the same question
 *  before it can say anything useful when the answer is none — and two copies
 *  of this filter would eventually disagree about what is quantisable.
 */
export function quantisable(models: LocalModel[]): LocalModel[] {
  return models.filter(
    (m) => m.category === 'image' && !m.mflux_base && m.size_gb > 1,
  );
}

// What a model of this size costs to hold, roughly, at a given bit width.
function estimate(model: LocalModel, bits: number): string {
  if (!model.size_gb) return '';
  // Source is bf16 — 16 bits per weight.
  return `~${((model.size_gb * bits) / 16).toFixed(1)} GB`;
}

// Architectures mflux has no implementation for. Quantising is not a format
// conversion — mflux has to know the model's structure to rebuild it — so an
// SDXL or SD3 checkpoint cannot go through this no matter which base is picked.
const UNSUPPORTED = /\b(sdxl|sd3|sd-3|pony|illustrious|noobai|stable[-\s]?diffusion|xl)\b/i;

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
  if (n.includes('qwen') && has('qwen_image')) return 'qwen_image';
  if (n.includes('schnell') && has('schnell')) return 'schnell';
  if (n.includes('flux') && has('dev')) return 'dev';
  // No guess rather than a wrong one: defaulting to whatever sorted first sends
  // the build off against an unrelated architecture and it fails minutes later.
  return '';
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
  const [qBits, setQBits] = useState(6);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Anything already stored as MLX shards is done; offering to requantise it
  // would just be a lossy copy of a lossy copy.
  const candidates = quantisable(models);

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
  const unsupported = !!model && UNSUPPORTED.test(model.name);

  useEffect(() => {
    if (!model || !bases.length) return;
    setBase(guessBase(model.name, bases));
    setName(`${model.name} (${qBits}-bit MLX)`);
  }, [source, bases.length, qBits]);

  async function build() {
    if (!model || !base || !name.trim()) return;
    setError(null);
    try {
      await startQuantize({
        source: model.path, base, name: name.trim(),
        transformer_bits: qBits, encoder_bits: qBits,
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
            stays in memory instead of being rebuilt for every prompt. Lower
            precision buys memory, not speed — a bf16 matmul measured 13.6 TFLOPS
            against 11.9 for 4-bit — so pick the highest that fits. On a 24GB Mac
            that is usually 6-bit for a 9B model, 8-bit for anything smaller.
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
            <option value="">Choose…</option>
            {bases.map((b) => <option key={b.id} value={b.id}>{b.cli}</option>)}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Precision</span>
          <select className={select} value={qBits} onChange={(e) => setQBits(Number(e.target.value))}>
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
          disabled={!model || !base || !name.trim() || unsupported}
          className="btn-accent text-xs px-4 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Build
        </button>
      </div>

      {unsupported && (
        <p className="text-[11px] text-amber-400/90 mt-2 max-w-2xl leading-relaxed">
          mflux has no implementation for this architecture, so it cannot be quantised
          here — that needs the model's structure, not just its weights. SDXL-family
          models run on the diffusers path instead, which is fine for them: they are
          small enough that memory was never the problem.
        </p>
      )}
      {model && !unsupported && !base && (
        <p className="text-[11px] text-amber-400/90 mt-2">
          Pick which base model this is built on — the guess failed, and the wrong one
          fails minutes into the build rather than immediately.
        </p>
      )}
      {model && !unsupported && (
        <p className="text-[11px] text-[var(--text-faint)] mt-2">
          {model.size_gb} GB → {estimate(model, qBits)} · a few minutes, and the
          machine will be busy.
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
