/** Recipes: saved procedures, visible and editable.
 *
 *  The reason this screen exists rather than the recipes living quietly in a
 *  settings file: a recipe influences what happens. One that has become wrong
 *  should be findable and fixable, not invisible state somebody has to guess
 *  at — the same argument that made the project memory notes editable.
 *
 *  Running one prompts exactly as typing the steps would. That is worth saying
 *  on the screen, because the natural assumption about a saved procedure is
 *  the opposite.
 */

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, ChefHat, Play, Plus, Trash2, X } from 'lucide-react';

import {
  createRecipe, deleteRecipe, getIntegrations, getRecipes, runRecipe,
  type IntegrationsState, type RecipeInfo, type RecipeRun,
} from '../lib/sidecar';

export default function RecipesView() {
  const [recipes, setRecipes] = useState<RecipeInfo[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationsState | null>(null);
  const [runs, setRuns] = useState<Record<string, RecipeRun>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);

  const load = useCallback(() => {
    getRecipes().then(setRecipes).catch(() => undefined);
    getIntegrations().then(setIntegrations).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  async function start(recipe: RecipeInfo, values: Record<string, string>) {
    setBusy(recipe.id);
    setError(null);
    try {
      setRuns({ ...runs, [recipe.id]: await runRecipe(recipe.id, values) });
      load();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 flex flex-col gap-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-base flex items-center gap-2">
              <ChefHat size={18} /> Recipes
            </h1>
            <p className="text-[11px] text-[var(--text-faint)] mt-1 leading-relaxed
                          max-w-[60ch]">
              Something you do often, written down once. Each step runs through the
              same permissions as if you had typed it — a recipe is a shortcut for
              your fingers, never a way around being asked.
            </p>
          </div>
          <button onClick={() => setComposing(!composing)}
                  className="shrink-0 flex items-center gap-1.5 text-[11px]
                             btn-accent px-3 py-1.5 rounded-full transition">
            {composing ? <X size={12} /> : <Plus size={12} />}
            {composing ? 'Cancel' : 'New recipe'}
          </button>
        </div>

        {error && (
          <p className="text-[11px] text-rose-400 flex items-start gap-2">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}

        {composing && (
          <Composer
            capabilities={Object.keys(integrations?.capabilities ?? {}).sort()}
            onDone={() => { setComposing(false); load(); }}
            onError={setError} />
        )}

        {recipes.length === 0 && !composing && (
          <p className="text-[11px] text-[var(--text-faint)]">
            None yet.
          </p>
        )}

        <div className="flex flex-col gap-3">
          {recipes.map((recipe) => (
            <Card key={recipe.id} recipe={recipe} run={runs[recipe.id]}
                  busy={busy === recipe.id}
                  onRun={(values) => start(recipe, values)}
                  onDelete={async () => {
                    await deleteRecipe(recipe.id);
                    load();
                  }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Card({ recipe, run, busy, onRun, onDelete }: {
  recipe: RecipeInfo; run?: RecipeRun; busy: boolean;
  onRun: (values: Record<string, string>) => void;
  onDelete: () => void;
}) {
  const parameters = recipe.payload.parameters ?? {};
  const steps = recipe.payload.steps ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const ready = Object.keys(parameters).every((name) => values[name]?.trim());

  return (
    <section className="card p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm">{recipe.name}</h2>
          {recipe.description && (
            <p className="text-[11px] text-[var(--text-faint)] mt-0.5 leading-relaxed">
              {recipe.description}
            </p>
          )}
          <p className="text-[10px] text-[var(--text-faint)] mt-1">
            {steps.length} step{steps.length === 1 ? '' : 's'}
            {recipe.uses > 0 && ` · used ${recipe.uses}×`}
          </p>
        </div>
        <button onClick={onDelete}
                className="shrink-0 text-[var(--text-faint)] hover:text-rose-400
                           transition">
          <Trash2 size={13} />
        </button>
      </div>

      <ol className="flex flex-col gap-1">
        {steps.map((step, n) => (
          <li key={n} className="text-[11px] flex items-baseline gap-2">
            <span className="text-[var(--text-faint)] font-mono w-4 shrink-0">
              {n + 1}
            </span>
            <span className="truncate">
              {step.note || step.capability || step.tool}
            </span>
            <span className="text-[10px] font-mono text-[var(--text-faint)]
                             ml-auto shrink-0">
              {step.capability || step.tool}
            </span>
          </li>
        ))}
      </ol>

      {Object.keys(parameters).length > 0 && (
        <div className="flex flex-col gap-2">
          {Object.entries(parameters).map(([name, description]) => (
            <label key={name} className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wide
                               text-[var(--text-faint)]">
                {name} — {description}
              </span>
              <input value={values[name] ?? ''}
                     onChange={(e) => setValues({ ...values, [name]: e.target.value })}
                     className="bg-[var(--bg-inset)] px-3 py-2 rounded-lg text-xs
                                outline-none font-mono" />
            </label>
          ))}
        </div>
      )}

      <button onClick={() => onRun(values)} disabled={busy || !ready}
              className="self-start flex items-center gap-1.5 text-[11px]
                         btn-accent px-3 py-1.5 rounded-full transition
                         disabled:opacity-30">
        <Play size={12} /> Run
      </button>

      {run && (
        <div className="flex flex-col gap-1 border-t border-[var(--border)] pt-3">
          {run.results.map((result) => (
            <div key={result.step} className="text-[11px]">
              <span className={result.ok ? 'text-emerald-400' : 'text-rose-400'}>
                {result.ok ? <Check size={11} className="inline" /> : '✕'}
              </span>{' '}
              <span>{result.what}</span>
              {result.error && (
                <span className="text-rose-400 font-mono"> — {result.error}</span>
              )}
              {result.ok && result.output && (
                <pre className="text-[10px] text-[var(--text-faint)] mt-1
                                whitespace-pre-wrap max-h-24 overflow-y-auto">
                  {result.output.slice(0, 600)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Writing a recipe.
 *
 *  Steps are chosen from the capabilities that actually exist, rather than
 *  typed: a recipe naming a capability that was never real is one that fails
 *  when somebody runs it, and the engine would refuse it at save time anyway.
 */
function Composer({ capabilities, onDone, onError }: {
  capabilities: string[]; onDone: () => void; onError: (e: string) => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [steps, setSteps] = useState<{ capability: string; note: string;
                                       argumentsText: string }[]>(
    [{ capability: capabilities[0] ?? '', note: '', argumentsText: '{}' }]);
  const [parameters, setParameters] = useState('');

  async function save() {
    let parsed;
    try {
      parsed = steps.map((step) => ({
        capability: step.capability,
        note: step.note,
        arguments: JSON.parse(step.argumentsText || '{}'),
      }));
    } catch {
      onError('One of the steps has arguments that are not valid JSON.');
      return;
    }
    const declared: Record<string, string> = {};
    for (const line of parameters.split('\n')) {
      const [key, ...rest] = line.split(':');
      if (key.trim()) declared[key.trim()] = rest.join(':').trim() || key.trim();
    }
    try {
      await createRecipe({ name, description, steps: parsed,
                           parameters: declared });
      onDone();
    } catch (e) {
      onError(String((e as Error).message ?? e));
    }
  }

  return (
    <section className="card p-4 flex flex-col gap-3">
      <Text label="Name" value={name} onChange={setName}
            placeholder="Weekly summary" />
      <Text label="What it does" value={description} onChange={setDescription}
            placeholder="Read the sales sheet and draft a note about it" />
      <Text label="Parameters — one per line, name: description"
            value={parameters} onChange={setParameters}
            placeholder="path: which spreadsheet" multiline />

      <div className="flex flex-col gap-2">
        {steps.map((step, n) => (
          <div key={n} className="flex flex-col gap-1 p-2 rounded-lg
                                  bg-[var(--bg-inset)]">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-[var(--text-faint)]">
                {n + 1}
              </span>
              <select value={step.capability}
                      onChange={(e) => setSteps(steps.map((s, i) =>
                        i === n ? { ...s, capability: e.target.value } : s))}
                      className="flex-1 bg-[var(--bg)] px-2 py-1 rounded text-[11px]
                                 outline-none font-mono">
                {capabilities.map((capability) => (
                  <option key={capability} value={capability}>{capability}</option>
                ))}
              </select>
              {steps.length > 1 && (
                <button onClick={() => setSteps(steps.filter((_, i) => i !== n))}
                        className="text-[var(--text-faint)] hover:text-rose-400">
                  <X size={12} />
                </button>
              )}
            </div>
            <input value={step.note} placeholder="what this step is for"
                   onChange={(e) => setSteps(steps.map((s, i) =>
                     i === n ? { ...s, note: e.target.value } : s))}
                   className="bg-[var(--bg)] px-2 py-1 rounded text-[11px]
                              outline-none" />
            <input value={step.argumentsText}
                   placeholder='{"path": "{path}"}'
                   onChange={(e) => setSteps(steps.map((s, i) =>
                     i === n ? { ...s, argumentsText: e.target.value } : s))}
                   className="bg-[var(--bg)] px-2 py-1 rounded text-[11px]
                              outline-none font-mono" />
          </div>
        ))}
        <button
          onClick={() => setSteps([...steps, {
            capability: capabilities[0] ?? '', note: '', argumentsText: '{}' }])}
          className="self-start text-[11px] text-[var(--text-dim)]
                     hover:text-[var(--text)] transition">
          + Add a step
        </button>
      </div>

      {capabilities.length === 0 && (
        <p className="text-[11px] text-amber-400 leading-relaxed">
          Nothing is connected yet, so there are no capabilities to build a
          recipe from. Connect something in Settings first.
        </p>
      )}

      <button onClick={save} disabled={!name.trim() || capabilities.length === 0}
              className="self-start text-[11px] btn-accent px-3 py-1.5 rounded-full
                         transition disabled:opacity-30">
        Save
      </button>
    </section>
  );
}

function Text({ label, value, onChange, placeholder, multiline }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; multiline?: boolean;
}) {
  const shared = `bg-[var(--bg-inset)] px-3 py-2 rounded-lg text-xs outline-none
                  placeholder:text-[var(--text-faint)]`;
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-faint)]">
        {label}
      </span>
      {multiline
        ? <textarea value={value} placeholder={placeholder} rows={2}
                    onChange={(e) => onChange(e.target.value)}
                    className={`${shared} font-mono`} />
        : <input value={value} placeholder={placeholder}
                 onChange={(e) => onChange(e.target.value)}
                 className={shared} />}
    </label>
  );
}
