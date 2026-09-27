import ActivityOrb from '../components/ActivityOrb';
/** Fine-tuning a language model on your own examples, locally.
 *
 *  The screen is arranged around one fact: a training run that fails does not
 *  fail quickly. It either dies forty minutes in, or succeeds and produces an
 *  adapter that quietly makes the model worse. Both cost somebody an afternoon,
 *  and both are knowable in milliseconds beforehand.
 *
 *  So nothing here offers a Start button until the engine has read the dataset
 *  and sized the run. What comes back — the line numbers of unusable examples,
 *  how repetitive the set is, how much memory this machine can spare — is shown
 *  while the person is still deciding, which is the only moment it is useful.
 *
 *  The other honesty is about what an adapter is. It is not a model, it will
 *  not load without the one it was trained against, and the card written beside
 *  the weights says so — because six weeks later nobody remembers.
 */

import { useCallback, useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { AlertTriangle, Ban, Check, FileJson, GraduationCap, Trash2, Copy, SlidersHorizontal } from 'lucide-react';

import { cancelTraining, forgetAdapter, getAdapters, getLibrary,
         getTrainingJobs, getTrainingPresets, prepareTraining, startTraining,
         type AdapterCard, type LocalModel, type TrainingJob,
         type TrainingPlan, type TrainingPreset, type TrainingOptions } from '../lib/sidecar';
import OnTheComputer from '../components/OnTheComputer';
import { inDesktop } from '../lib/platform';
import { useLibraryVersion } from '../lib/library-changed';

export default function TrainingView() {
  const libraryVersion = useLibraryVersion();
  const [models, setModels] = useState<LocalModel[]>([]);
  const [presets, setPresets] = useState<TrainingPreset[]>([]);
  const [modelPath, setModelPath] = useState('');
  const [dataset, setDataset] = useState('');
  const [preset, setPreset] = useState('standard');
  const [name, setName] = useState('');
  const [options, setOptions] = useState<TrainingOptions>({});
  const [copied, setCopied] = useState(false);
  const [plan, setPlan] = useState<TrainingPlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [adapters, setAdapters] = useState<AdapterCard[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getTrainingJobs().then(setJobs).catch(() => undefined);
    getAdapters().then(setAdapters).catch(() => undefined);
  }, []);

  useEffect(() => {
    getLibrary()
      .then((all) => setModels(all.filter((m) => m.category === 'text' && m.engine === 'mlx' && m.ready)))
      .catch(() => undefined);
    getTrainingPresets().then(setPresets).catch(() => undefined);
    refresh();
  }, [refresh, libraryVersion]);

  // Only while something is running. A timer that keeps firing on an idle
  // screen is a fan that never stops on a laptop.
  const running = jobs.some((j) => ['pending', 'preparing', 'training'].includes(j.status));
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [running, refresh]);

  // Re-planned whenever either input changes, because the answer depends on
  // both and a stale plan is worse than none.
  useEffect(() => {
    let cancelled = false;
    setPlan(null);
    if (!modelPath || !dataset) { setPlanning(false); return; }
    setPlanning(true);
    setError(null);
    const timer = window.setTimeout(() => {
      prepareTraining({ model_path: modelPath, dataset_path: dataset, preset, options })
        .then((next) => { if (!cancelled) setPlan(next); })
        .catch((e) => { if (!cancelled) setError(String(e.message ?? e)); })
        .finally(() => { if (!cancelled) setPlanning(false); });
    }, 300);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [modelPath, dataset, preset, options]);

  async function pickDataset() {
    const picked = await open({
      multiple: false, title: 'Choose a training file',
      filters: [{ name: 'Examples', extensions: ['jsonl'] }],
    });
    if (typeof picked === 'string') setDataset(picked);
  }

  async function start() {
    setError(null);
    try {
      await startTraining({ model_path: modelPath, dataset_path: dataset, preset, name, options });
      refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  const ready = !!plan?.dataset.usable && !!plan?.estimate.feasible && !planning && !running;
  const selectedPreset = presets.find((item) => item.id === preset);
  const effective = { iterations: 600, batch_size: 4, rank: 16, learning_rate: 0.00001,
    num_layers: 8, max_seq_length: 2048, grad_checkpoint: true, ...selectedPreset, ...options };
  const selectedModel = models.find((model) => model.path === modelPath);
  const controls = [
    { key: 'iterations', label: 'Training steps', hint: 'How many updates to make.', min: 10, max: 100000, step: 10 },
    { key: 'batch_size', label: 'Batch size', hint: 'Examples per step. Smaller uses less memory.', min: 1, max: 8, step: 1 },
    { key: 'learning_rate', label: 'Learning rate', hint: 'How much each update changes the adapter.', min: 0.0000001, max: 0.001, step: 0.000001 },
    { key: 'rank', label: 'Adapter rank', hint: 'Adapter capacity. Higher needs more memory.', min: 4, max: 64, step: 4 },
    { key: 'num_layers', label: 'Layers to train', hint: 'Last transformer layers to adapt.', min: 1, max: 64, step: 1 },
    { key: 'max_seq_length', label: 'Example length', hint: 'Maximum tokens per example; longer text is truncated.', min: 256, max: 8192, step: 256 },
  ] as const;
  async function copyExample() {
    try {
      await navigator.clipboard.writeText(JSON.stringify({ messages: [
        { role: 'user', content: 'Summarize this project in one sentence.' },
        { role: 'assistant', content: 'A local assistant that helps people work with their own documents.' },
      ] }) + '\n');
      setCopied(true);
    } catch { setError('Could not copy. Select and copy the example below.'); }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="page-column flex flex-col gap-6">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <GraduationCap size={18} /> Training
          </h1>
          <p className="text-sm text-[var(--text-dim)] mt-2 leading-relaxed">
            Teach a model using your own examples. Training runs locally and creates
            a small adapter to use with the original model.
          </p>
        </div>

        {/* ------------------------------------------------------ set it up */}
        <section className="card p-6 flex flex-col gap-6">
          <div className="training-section-title"><span>01</span><h2>Base model &amp; adapter</h2></div>
          <label className="field"><span className="label">Adapter name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. My research assistant" maxLength={80} />
          </label>
          <div>
            <label className="text-xs">Model</label>
            <select value={modelPath} onChange={(e) => setModelPath(e.target.value)}
                    className="input mt-2">
              <option value="">Choose a model on this computer…</option>
              {models.map((m) => (
                <option key={m.id} value={m.path}>{m.name}</option>
              ))}
            </select>
            {models.length === 0 && (
              <p className="text-[11px] text-[var(--text-faint)] mt-1">
                No compatible MLX text models are installed. Add one from the Library to train locally on Apple Silicon.
              </p>
            )}
          </div>

          {selectedModel && <p className="text-xs text-[var(--text-dim)]">Base weights: {selectedModel.size_gb.toFixed(1)} GB · Original model stays unchanged</p>}
        </section>
        <section className="card p-6 flex flex-col gap-4">
          <div className="training-section-title"><span>02</span><h2>Training examples</h2></div>
          <div>
            <label className="text-xs">Dataset · JSONL</label>
            {!inDesktop() && <div className="mt-1"><OnTheComputer>Training files are chosen on the computer running Uncloud.</OnTheComputer></div>}
            <button onClick={pickDataset} disabled={!inDesktop()}
                    className="w-full mt-1 flex items-center justify-between gap-3
                               bg-[var(--bg-inset)] px-3 py-2 rounded-lg text-xs
                               text-left hover:brightness-110 transition">
              <span className={dataset ? '' : 'text-[var(--text-faint)]'}>
                {dataset || 'Choose a .jsonl file…'}
              </span>
              <FileJson size={13} className="text-[var(--text-dim)] shrink-0" />
            </button>
            <p className="text-[11px] text-[var(--text-faint)] mt-1 leading-relaxed">
              One example per line, as either a <code>messages</code> list or a
              <code> prompt</code>/<code>completion</code> pair.
            </p>
          </div>

          <details className="training-disclosure">
            <summary>How to prepare your examples</summary>
            <div className="mt-3 flex flex-col gap-3 text-xs text-[var(--text-dim)]">
              <p>Use one JSON object per line. Include varied questions and the answers you want the model to learn. Remove private information you do not want in the adapter.</p>
              <pre className="bg-[var(--bg-inset)] p-3 rounded-lg overflow-x-auto">{'{"messages":[{"role":"user","content":"Your question"},{"role":"assistant","content":"Your ideal answer"}]}'}</pre>
              <button className="pill self-start" onClick={copyExample}><Copy size={14} />{copied ? 'Example copied' : 'Copy an example'}</button>
              <p>Save the file with a .jsonl extension. Uncloud checks its format and holds back validation examples when the dataset is large enough.</p>
            </div>
          </details>
        </section>
        <section className="card p-6 flex flex-col gap-5">
          <div className="training-section-title"><span>03</span><h2>Training settings</h2></div>
          <div>
            <label className="text-xs">Starting preset</label>
            <div className="training-presets mt-2">
              {presets.map((option) => (
                <button key={option.id} onClick={() => { setPreset(option.id); setOptions({}); }} aria-pressed={preset === option.id}
                        className={`text-left px-3 py-3 rounded-lg transition ${
                          preset === option.id
                            ? 'bg-[var(--bg-inset)] ring-1 ring-[var(--border-strong)]'
                            : 'hover:bg-[var(--bg-inset)]'}`}>
                  <div className="text-sm flex items-center justify-between">{option.label}{preset === option.id && <Check size={15} />}</div>
                  <div className="text-[11px] text-[var(--text-faint)]">
                    {option.note}
                  </div>
                </button>
              ))}
            </div>
          </div>
          <details className="training-disclosure">
            <summary className="flex items-center gap-2"><SlidersHorizontal size={15} />Customize settings</summary>
            <div className="training-controls mt-4">
              {controls.map(({ key, label, hint, min, max, step }) => <label className="field" key={key}>
                <span className="label">{label}</span>
                <input className="input" type="number" min={min} max={max} step={step} value={effective[key]}
                  onChange={(e) => setOptions((current) => ({ ...current, [key]: e.target.value === '' ? min : Number(e.target.value) }))} />
                <span className="text-xs text-[var(--text-faint)]">{hint}</span>
              </label>)}
            </div>
            <label className="flex items-start gap-3 mt-5 text-sm">
              <input type="checkbox" checked={effective.grad_checkpoint} onChange={(e) => setOptions((current) => ({ ...current, grad_checkpoint: e.target.checked }))} />
              <span>Save memory<span className="block text-xs text-[var(--text-faint)]">Recompute intermediate values during training. Uses less memory but may take longer.</span></span>
            </label>
            <button className="pill mt-3" onClick={() => setOptions({})}>Reset to preset</button>
          </details>
          <p className="text-xs text-[var(--text-dim)]">{effective.iterations.toLocaleString()} steps · Batch {effective.batch_size} · Rank {effective.rank} · {effective.max_seq_length.toLocaleString()} tokens</p>
        </section>

        {/* ------------------------------------------- what would happen */}
        {planning && (
          <p className="text-[11px] text-[var(--text-faint)] flex items-center gap-2">
            <ActivityOrb state="working" size={20} label="Working…" /> Reading the examples…
          </p>
        )}

        {plan && <Plan plan={plan} />}
        {error && <p className="text-[11px] text-rose-400">{error}</p>}

        <div className="training-start">
          <div><h2 className="text-sm">{ready ? 'Ready to train' : planning ? 'Checking your setup…' : running ? 'A training run is active' : 'Review your setup'}</h2>
            <p className="text-xs text-[var(--text-dim)] mt-1">{!modelPath ? 'Choose a compatible base model to begin.' : !dataset ? 'Choose your examples to check quality and memory use.' : ready ? 'Creates an adapter. It still needs the original base model.' : 'Resolve the checks above before starting.'}</p>
          </div>
          <button onClick={start} disabled={!ready} className="btn-accent px-5 py-2.5 rounded-lg shrink-0">Start training</button>
        </div>

        {/* --------------------------------------------------------- runs */}
        {jobs.length > 0 && (
          <section className="card p-4">
            <h2 className="text-sm mb-2">Runs</h2>
            <div className="flex flex-col gap-3">
              {jobs.map((job) => <Job key={job.id} job={job} onChange={refresh} />)}
            </div>
          </section>
        )}

        {/* ----------------------------------------------------- adapters */}
        {adapters.length > 0 && (
          <section className="card p-4">
            <h2 className="text-sm mb-1">Adapters</h2>
            <p className="text-[11px] text-[var(--text-faint)] mb-3">
              Each one only works with the model it was trained against.
            </p>
            <div className="flex flex-col gap-2">
              {adapters.map((adapter) => (
                <div key={adapter.path}
                     className="flex items-start justify-between gap-3 px-3 py-2
                                rounded-lg bg-[var(--bg-inset)]">
                  <div className="min-w-0">
                    <div className="text-xs">{adapter.adapter}</div>
                    <div className="text-[11px] text-[var(--text-faint)] mt-0.5 truncate">
                      {adapter.base_model.split('/').pop()} · {adapter.examples} examples
                      {adapter.val_loss != null && ` · val loss ${adapter.val_loss}`}
                    </div>
                  </div>
                  <button onClick={() => forgetAdapter(adapter.adapter).then(refresh)}
                          className="shrink-0 text-[var(--text-faint)]
                                     hover:text-rose-400 transition">
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/** What the run would cost, before it costs it. */
function Plan({ plan }: { plan: TrainingPlan }) {
  const { dataset, estimate } = plan;
  return (
    <section className="card p-4 flex flex-col gap-3">
      <div className="flex items-baseline gap-3 flex-wrap text-xs">
        <span>{dataset.count} examples</span>
        <span className="text-[var(--text-faint)]">
          {(dataset.variety * 100).toFixed(0)}% distinct
        </span>
        {estimate.feasible && (
          <span className="text-[var(--text-faint)]">
            about {estimate.memory_gb} GB · {estimate.time}
          </span>
        )}
      </div>

      {!dataset.usable && (
        <p className="text-[11px] text-rose-400 flex items-start gap-2">
          <Ban size={13} className="mt-0.5 shrink-0" />
          These examples need changes before training.
        </p>
      )}

      {dataset.warnings.map((warning) => (
        <p key={warning}
           className="text-[11px] text-amber-400 flex items-start gap-2 leading-relaxed">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {warning}
        </p>
      ))}

      {dataset.problems.length > 0 && (
        <div>
          <p className="text-[11px] text-[var(--text-faint)] mb-1">
            {dataset.problem_count} line
            {dataset.problem_count === 1 ? '' : 's'} could not be used:
          </p>
          <div className="flex flex-col gap-0.5 max-h-32 overflow-y-auto">
            {dataset.problems.map((problem, n) => (
              <div key={n} className="text-[11px] font-mono text-[var(--text-dim)]">
                line {problem.line}: {problem.what}
              </div>
            ))}
          </div>
        </div>
      )}

      {!estimate.feasible && estimate.reason && (
        <p className="text-[11px] text-amber-400 leading-relaxed flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          {estimate.reason}
        </p>
      )}

      {dataset.usable && estimate.feasible && dataset.warnings.length === 0 && (
        <p className="text-[11px] text-emerald-400 flex items-center gap-2">
          <Check size={13} /> Dataset checks passed. Quality still needs to be evaluated after training.
        </p>
      )}
    </section>
  );
}

function Job({ job, onChange }: { job: TrainingJob; onChange: () => void }) {
  const running = ['pending', 'preparing', 'training'].includes(job.status);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs truncate">
          {job.model_path.split('/').pop()} · {job.preset}
        </span>
        {running ? (
          <button onClick={() => cancelTraining(job.id).then(onChange)}
                  className="text-[11px] text-[var(--text-faint)]
                             hover:text-rose-400 transition">
            Stop
          </button>
        ) : (
          <span className={`text-[11px] ${
            job.status === 'done' ? 'text-emerald-400'
            : job.status === 'error' ? 'text-rose-400'
            : 'text-[var(--text-faint)]'}`}>
            {job.status}
          </span>
        )}
      </div>

      {running && (
        <>
          <div className="h-1 rounded-full bg-[var(--bg-inset)] overflow-hidden">
            <div className="h-full accent-bar transition-[width] duration-500"
                 style={{ width: `${Math.max(2, job.percent)}%` }} />
          </div>
          <div className="text-[11px] text-[var(--text-faint)] font-mono">
            {/* Read from the trainer's own output. A bar driven by a clock is a
                lie the moment the machine gets busy, and this is exactly the
                kind of job somebody walks away from. */}
            iteration {job.iteration} of {job.iterations}
            {job.train_loss != null && ` · loss ${job.train_loss}`}
            {job.val_loss != null && ` · val ${job.val_loss}`}
          </div>
        </>
      )}

      {job.status === 'error' && job.error && (
        <p className="text-[11px] text-rose-400 font-mono break-all">{job.error}</p>
      )}
    </div>
  );
}
