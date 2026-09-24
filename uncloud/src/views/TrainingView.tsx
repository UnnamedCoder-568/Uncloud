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
import { AlertTriangle, Ban, Check, FileJson, GraduationCap, Trash2 } from 'lucide-react';

import { cancelTraining, forgetAdapter, getAdapters, getLibrary,
         getTrainingJobs, getTrainingPresets, prepareTraining, startTraining,
         type AdapterCard, type LocalModel, type TrainingJob,
         type TrainingPlan, type TrainingPreset } from '../lib/sidecar';
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
      .then((all) => setModels(all.filter((m) => m.category === 'text')))
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
    if (!modelPath || !dataset) { setPlan(null); return; }
    setPlanning(true);
    setError(null);
    prepareTraining({ model_path: modelPath, dataset_path: dataset, preset })
      .then(setPlan)
      .catch((e) => { setPlan(null); setError(String(e.message ?? e)); })
      .finally(() => setPlanning(false));
  }, [modelPath, dataset, preset]);

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
      await startTraining({ model_path: modelPath, dataset_path: dataset, preset });
      refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  const ready = !!plan?.dataset.usable && !!plan?.estimate.feasible;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 flex flex-col gap-4">
        <div>
          <h1 className="text-base flex items-center gap-2">
            <GraduationCap size={18} /> Training
          </h1>
          <p className="text-[11px] text-[var(--text-faint)] mt-1 leading-relaxed">
            Teach a model a consistent behaviour from your own examples. It runs
            on this machine, your examples never leave it, and what comes out is
            an adapter — a small file that works with the model it was trained
            against, not a copy of it.
          </p>
        </div>

        {/* ------------------------------------------------------ set it up */}
        <section className="card p-4 flex flex-col gap-3">
          <div>
            <label className="text-xs">Model</label>
            <select value={modelPath} onChange={(e) => setModelPath(e.target.value)}
                    className="w-full mt-1 bg-[var(--bg-inset)] px-3 py-2 rounded-lg
                               text-xs outline-none">
              <option value="">Choose a model on this computer…</option>
              {models.map((m) => (
                <option key={m.id} value={m.path}>{m.name}</option>
              ))}
            </select>
            {models.length === 0 && (
              <p className="text-[11px] text-[var(--text-faint)] mt-1">
                No text models are installed yet. Download one from Models first.
              </p>
            )}
          </div>

          <div>
            <label className="text-xs">Examples</label>
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

          <div>
            <label className="text-xs">How much to change</label>
            <div className="flex flex-col gap-1.5 mt-1">
              {presets.map((option) => (
                <button key={option.id} onClick={() => setPreset(option.id)}
                        className={`text-left px-3 py-2 rounded-lg transition ${
                          preset === option.id
                            ? 'bg-[var(--bg-inset)] ring-1 ring-[var(--accent)]'
                            : 'hover:bg-[var(--bg-inset)]'}`}>
                  <div className="text-xs">{option.label}</div>
                  <div className="text-[11px] text-[var(--text-faint)]">
                    {option.note}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* ------------------------------------------- what would happen */}
        {planning && (
          <p className="text-[11px] text-[var(--text-faint)] flex items-center gap-2">
            <ActivityOrb state="working" size={20} label="Working…" /> Reading the examples…
          </p>
        )}

        {plan && <Plan plan={plan} />}
        {error && <p className="text-[11px] text-rose-400">{error}</p>}

        {plan && (
          <button onClick={start} disabled={!ready}
                  className="grad-button text-sm self-start disabled:opacity-30">
            {ready ? 'Start training' : 'Cannot start'}
          </button>
        )}

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
          These examples cannot be trained on.
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
          <Check size={13} /> Nothing here looks wrong.
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
