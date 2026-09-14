import { useEffect, useState } from 'react';
import DevicesSection from '../components/DevicesSection';
import UpdatesSection from '../components/UpdatesSection';
import IntegrationsSection from '../components/IntegrationsSection';
import PermissionsSection from '../components/PermissionsSection';
import LegalSection from '../components/LegalSection';
import { open } from '@tauri-apps/plugin-dialog';
import { setModelsDir, setDeviceAccess, setHfToken, getSettings, setKeepAwake, getAgentTools, setAgentToolGroups, setOutputDir, getResident, stopAllModels, getWeightCache, clearWeightCache } from '../lib/sidecar';
import type { Settings, AgentTools, ResidentModels } from '../lib/sidecar';
import { formatBytes } from '../lib/format';
import OnTheComputer from '../components/OnTheComputer';
import { inDesktop } from '../lib/platform';

export default function SettingsView() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [tokenInput, setTokenInput] = useState('');
  const [tokenSaved, setTokenSaved] = useState(false);

  useEffect(() => {
    getSettings().then(setSettings);
  }, []);

  async function saveToken() {
    if (!tokenInput.trim()) return;
    await setHfToken(tokenInput.trim());
    setTokenInput('');
    setTokenSaved(true);
    setSettings((s) => (s ? { ...s, hf_token_set: true } : s));
    setTimeout(() => setTokenSaved(false), 2000);
  }

  async function changeFolder() {
    const selected = await open({ directory: true, multiple: false, defaultPath: settings?.models_dir });
    if (typeof selected === 'string') {
      await setModelsDir(selected);
      setSettings((s) => (s ? { ...s, models_dir: selected } : s));
    }
  }

  const [resident, setResident] = useState<ResidentModels | null>(null);
  const [stopping, setStopping] = useState(false);
  const [cacheBytes, setCacheBytes] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    getWeightCache().then((c) => setCacheBytes(c.bytes)).catch(() => undefined);
  }, []);

  async function clearCache() {
    setClearing(true);
    try {
      await clearWeightCache();
      setCacheBytes((await getWeightCache().catch(() => null))?.bytes ?? 0);
    } finally {
      setClearing(false);
    }
  }

  // Polled, because a model can be loaded by any tab at any time.
  useEffect(() => {
    const read = () => getResident().then(setResident).catch(() => undefined);
    read();
    const t = setInterval(read, 4000);
    return () => clearInterval(t);
  }, []);

  async function stopModels() {
    setStopping(true);
    try {
      await stopAllModels();
      setResident(await getResident().catch(() => null));
    } finally {
      setStopping(false);
    }
  }

  async function changeOutputFolder() {
    const selected = await open({ directory: true, multiple: false, defaultPath: settings?.output_dir });
    if (typeof selected === 'string') {
      await setOutputDir(selected);
      setSettings((s) => (s ? { ...s, output_dir: selected, output_dir_is_default: false } : s));
    }
  }

  async function toggleDeviceAccess() {
    if (!settings) return;
    const next = !settings.agent_device_access;
    if (next && !confirm('Chisel will be able to run shell commands and read/write anywhere on this Mac, not just its workspace folder. Continue?')) {
      return;
    }
    await setDeviceAccess(next);
    setSettings({ ...settings, agent_device_access: next });
  }

  const [tools, setTools] = useState<AgentTools | null>(null);

  useEffect(() => {
    getAgentTools().then(setTools).catch(() => setTools(null));
  }, []);

  async function applyGroups(next: string[] | null) {
    await setAgentToolGroups(next);
    setTools(await getAgentTools());
  }

  function toggleGroup(id: string) {
    if (!tools) return;
    const base = tools.resolved;
    const next = base.includes(id) ? base.filter((g) => g !== id) : [...base, id];
    applyGroups(next);
  }

  async function toggleKeepAwake() {
    if (!settings) return;
    const next = !settings.keep_awake;
    await setKeepAwake(next);
    setSettings({ ...settings, keep_awake: next });
  }

  if (!settings) return null;

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <h1 className="text-2xl font-semibold mb-6">Settings</h1>

      <div className="max-w-xl flex flex-col gap-4">
        <section className="card p-4">
          <h2 className="text-sm mb-1">Models folder</h2>
          <p className="text-[11px] text-[var(--text-faint)] mb-3">
            Where Uncloud looks for and downloads models.
          </p>
          <button
            onClick={changeFolder}
            disabled={!inDesktop()}
            className="w-full bg-[var(--bg-inset)] px-3 py-2.5 rounded-lg text-xs text-left hover:bg-[var(--bg-inset)]/70 transition font-mono break-all disabled:hover:bg-[var(--bg-inset)] disabled:cursor-default"
          >
            {settings.models_dir}
          </button>
          {!inDesktop() && <div className="mt-2"><OnTheComputer /></div>}
        </section>

        <section className="card p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="text-sm mb-1">Converted weight cache</h2>
              <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                Some models are stored in a form that has to be converted before it
                can be used — fp8 checkpoints and GGUF encoders. The result is kept
                here so it is done once instead of before every generation. Clearing
                it frees the space and costs that conversion time again.
              </p>
              <p className="text-[11px] text-[var(--text-dim)] font-mono mt-2">
                {cacheBytes === null ? '—' : formatBytes(cacheBytes)}
              </p>
            </div>
            <button
              onClick={clearCache}
              disabled={!cacheBytes || clearing}
              className="text-[11px] px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white disabled:opacity-30 transition shrink-0"
            >
              {clearing ? 'Clearing…' : 'Clear'}
            </button>
          </div>
        </section>

        {resident && (
          <section className="card p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-sm mb-1">Models in memory</h2>
                {resident.anything ? (
                  <ul className="text-[11px] text-[var(--text-dim)] font-mono leading-relaxed">
                    {([
                      ['Chat', resident.text_model],
                      ['Image', resident.image_pipeline],
                      ['Image (MLX)', resident.mflux_model],
                      ['Image (assembled)', resident.flux2_profile],
                      ['Video', resident.video_pipeline],
                    ] as [string, string | null][])
                      .filter(([, v]) => v)
                      .map(([k, v]) => (
                        <li key={k} className="truncate">
                          <span className="text-[var(--text-faint)]">{k}: </span>
                          {v!.split('/').pop()}
                        </li>
                      ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                    Nothing loaded. Models are freed when you quit, but they stay
                    resident between generations so repeat runs are fast.
                  </p>
                )}
              </div>
              <button
                onClick={stopModels}
                disabled={!resident.anything || stopping}
                className="text-[11px] px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white disabled:opacity-30 transition shrink-0"
              >
                {stopping ? 'Stopping…' : 'Unload all'}
              </button>
            </div>
          </section>
        )}

        <section className="card p-4">
          <h2 className="text-sm mb-1">Where generated work is saved</h2>
          <p className="text-[11px] text-[var(--text-faint)] mb-3">
            Images, video, music and narration are written here. Pick somewhere you
            actually open — a folder in Documents or on a drive, not a hidden one.
          </p>
          <button
            onClick={changeOutputFolder}
            disabled={!inDesktop()}
            className="w-full bg-[var(--bg-inset)] px-3 py-2.5 rounded-lg text-xs text-left hover:bg-[var(--bg-inset)]/70 transition font-mono break-all disabled:hover:bg-[var(--bg-inset)] disabled:cursor-default"
          >
            {settings.output_dir}
          </button>
          {!inDesktop() && <div className="mt-2"><OnTheComputer /></div>}
          {settings.output_dir_is_default && (
            <p className="mt-2 text-[11px] text-amber-400/80">
              Still the default hidden folder. Choose somewhere of your own.
            </p>
          )}
        </section>

        <section className="card p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm mb-1">Chisel full device access</h2>
              <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                Off by default: Chisel's shell and filesystem tools are scoped to
                <code className="font-mono"> ~/.otto/workspace</code>. Turning this on lets the agent
                touch your whole Mac when you give it a goal.
              </p>
            </div>
            <button
              onClick={toggleDeviceAccess}
              className={`w-11 h-6 rounded-full shrink-0 transition relative ${settings.agent_device_access ? 'bg-emerald-500' : 'bg-[var(--border)]'}`}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition ${settings.agent_device_access ? 'left-5' : 'left-0.5'}`} />
            </button>
          </div>
        </section>

        <section className="card p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm mb-1">Keep this machine awake</h2>
              <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                Stops the machine sleeping while an image, music, narration or agent
                job is running. Without it a long job is suspended when the display
                times out, and you come back to it unfinished. Released as soon as
                the last job ends.
              </p>
            </div>
            <button
              onClick={toggleKeepAwake}
              className={`w-11 h-6 rounded-full shrink-0 transition relative ${settings.keep_awake ? 'accent-bar' : 'bg-[var(--border)]'}`}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition ${settings.keep_awake ? 'left-5' : 'left-0.5'}`} />
            </button>
          </div>
        </section>

        {tools && (
          <section className="card p-4">
            <div className="flex items-start justify-between gap-4 mb-3">
              <div>
                <h2 className="text-sm mb-1">Chisel tools</h2>
                <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                  Every tool's description goes into the planner's prompt, so a smaller
                  model plans better against fewer of them. Left automatic, the set is
                  chosen from the loaded model's size.
                </p>
              </div>
              <span className="text-[11px] text-[var(--text-dim)] tabular-nums shrink-0">
                {tools.active_count} active
              </span>
            </div>

            <button
              onClick={() => applyGroups(tools.configured === null ? tools.resolved : null)}
              className={`w-full mb-3 text-[11px] px-3 py-2 rounded-lg transition ${
                tools.configured === null
                  ? 'accent-bar text-white'
                  : 'bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white'
              }`}
            >
              {tools.configured === null ? 'Automatic — matched to the model' : 'Use automatic'}
            </button>

            <div className="flex flex-col gap-1.5">
              {tools.groups.map((g) => {
                const on = tools.resolved.includes(g.id);
                return (
                  <button
                    key={g.id}
                    onClick={() => toggleGroup(g.id)}
                    className={`flex items-start gap-3 text-left px-3 py-2 rounded-lg transition ${
                      on ? 'bg-[var(--bg-raised)]' : 'bg-transparent hover:bg-[var(--bg-raised)]/50'
                    }`}
                  >
                    <span
                      className={`mt-0.5 w-3.5 h-3.5 rounded shrink-0 ${
                        on ? 'accent-bar' : 'border border-[var(--border)]'
                      }`}
                    />
                    <span className="min-w-0">
                      <span className="text-xs block">
                        {g.label}
                        <span className="text-[var(--text-faint)]"> · {g.count}</span>
                      </span>
                      <span className="text-[10px] text-[var(--text-faint)] block leading-relaxed">
                        {g.note}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        <section className="card p-4">
          <h2 className="text-sm mb-1">Hugging Face token</h2>
          <p className="text-[11px] text-[var(--text-faint)] mb-3 max-w-sm">
            Needed for gated repos (e.g. Black Forest Labs' FLUX.2 license) and gives faster,
            unauthenticated-rate-limit-free downloads generally. Create one at{' '}
            <span className="font-mono">huggingface.co/settings/tokens</span>.
          </p>
          <div className="flex gap-2">
            <input
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder={settings.hf_token_set ? '•••••••••••••••• (saved)' : 'hf_...'}
              className="flex-1 bg-[var(--bg-inset)] px-3 py-2 rounded-lg text-xs outline-none font-mono placeholder:text-[var(--text-faint)]"
            />
            <button
              onClick={saveToken}
              disabled={!tokenInput.trim()}
              className="text-xs px-4 rounded-lg btn-accent disabled:opacity-30 transition"
            >
              {tokenSaved ? 'Saved' : 'Save'}
            </button>
          </div>
        </section>

        <PermissionsSection />

        <UpdatesSection />

        <DevicesSection />

        <IntegrationsSection />

        <LegalSection />

        <section className="card p-4">
          <h2 className="text-sm mb-1">About</h2>
          <p className="text-[11px] text-[var(--text-faint)]">Uncloud 0.1.0 — local-first AI studio.</p>
        </section>
      </div>
    </div>
  );
}
