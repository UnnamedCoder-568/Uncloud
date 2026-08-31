import { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { setModelsDir, setDeviceAccess, setHfToken, getSettings } from '../lib/sidecar';
import type { Settings } from '../lib/sidecar';

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

  async function toggleDeviceAccess() {
    if (!settings) return;
    const next = !settings.agent_device_access;
    if (next && !confirm('Agent Mode will be able to run shell commands and read/write anywhere on this Mac, not just its workspace folder. Continue?')) {
      return;
    }
    await setDeviceAccess(next);
    setSettings({ ...settings, agent_device_access: next });
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
            className="w-full bg-[var(--bg-inset)] px-3 py-2.5 rounded-lg text-xs text-left hover:bg-[var(--bg-inset)]/70 transition font-mono"
          >
            {settings.models_dir}
          </button>
        </section>

        <section className="card p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm mb-1">Agent full device access</h2>
              <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                Off by default: Agent Mode's shell and filesystem tools are scoped to
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
              className="text-xs px-4 rounded-lg bg-white text-black disabled:opacity-30 disabled:bg-[var(--border)] disabled:text-[var(--text-faint)] transition"
            >
              {tokenSaved ? 'Saved' : 'Save'}
            </button>
          </div>
        </section>

        <section className="card p-4">
          <h2 className="text-sm mb-1">About</h2>
          <p className="text-[11px] text-[var(--text-faint)]">Uncloud 0.1.0 — local-first AI studio.</p>
        </section>
      </div>
    </div>
  );
}
