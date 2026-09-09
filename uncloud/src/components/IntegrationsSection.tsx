/** Settings → Integrations: what Uncloud is connected to.
 *
 *  Two things this screen is careful about.
 *
 *  **It shows connectors that do not exist yet.** "Google Workspace needs an
 *  OAuth client you register with Google" and "we do not support that" send
 *  somebody in completely different directions, and hiding the row tells them
 *  the second when the first is true.
 *
 *  **It never displays a credential, because it never has one.** The engine
 *  returns a label — a folder, an address — and the secret lives in the
 *  keychain. There is nothing here to redact.
 */

import { useCallback, useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { AlertTriangle, Check, FolderOpen, Lock, Plug } from 'lucide-react';

import { connectIntegration, disconnectIntegration, getIntegrations,
         type IntegrationInfo, type IntegrationsState } from '../lib/sidecar';

export default function IntegrationsSection() {
  const [state, setState] = useState<IntegrationsState | null>(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(() => {
    getIntegrations().then(setState).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  async function chooseFolder(integration: IntegrationInfo) {
    const picked = await open({ directory: true, multiple: false,
                                title: `Choose a folder for ${integration.name}` });
    if (typeof picked !== 'string') return;
    setBusy(integration.id);
    try { setState(await connectIntegration(integration.id, { label: picked })); }
    finally { setBusy(''); }
  }

  async function disconnect(integration: IntegrationInfo) {
    setBusy(integration.id);
    try { setState(await disconnectIntegration(integration.id)); }
    finally { setBusy(''); }
  }

  if (!state) return null;

  const ready = state.integrations.filter((i) => i.available);
  const planned = state.integrations.filter((i) => !i.available);

  return (
    <section className="card p-4">
      <h2 className="text-sm mb-1">Integrations</h2>
      <p className="text-[11px] text-[var(--text-faint)] mb-3">
        What Uncloud can reach outside itself. Connecting something does not give
        the agent permission to use it — that is asked for when it happens, every
        time.
      </p>

      {!state.keychain && (
        <div className="flex items-start gap-2 text-[11px] text-amber-400 mb-3
                        border-l-2 border-amber-400/50 pl-3">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>
            There is no system keychain on this machine, so credentials would be
            kept in a file readable only by you. That is weaker than a keychain,
            and you should decide whether it is enough before connecting anything.
          </span>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {ready.map((integration) => (
          <div key={integration.id}
               className="flex items-start justify-between gap-3 px-3 py-2.5
                          rounded-lg bg-[var(--bg-inset)]">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Plug size={13} className="text-[var(--text-dim)]" />
                <span className="text-xs">{integration.name}</span>
                {integration.sensitivity === 'private' && (
                  <span className="flex items-center gap-1 text-[10px]
                                   text-[var(--text-faint)]">
                    <Lock size={10} /> stays local
                  </span>
                )}
              </div>
              <p className="text-[11px] text-[var(--text-faint)] mt-1 leading-relaxed">
                {integration.connected
                  ? integration.account
                  : integration.summary}
              </p>
            </div>
            {integration.connected ? (
              <button onClick={() => disconnect(integration)} disabled={!!busy}
                      className="shrink-0 text-[11px] px-3 py-1.5 rounded-full
                                 text-[var(--text-dim)] hover:text-[var(--text)]
                                 transition">
                Disconnect
              </button>
            ) : (
              <button onClick={() => chooseFolder(integration)} disabled={!!busy}
                      className="shrink-0 flex items-center gap-1.5 text-[11px]
                                 btn-accent px-3 py-1.5 rounded-full transition">
                <FolderOpen size={12} /> Choose folder
              </button>
            )}
          </div>
        ))}
      </div>

      {planned.length > 0 && (
        <div className="mt-4">
          <p className="text-[11px] text-[var(--text-faint)] mb-2">
            Not built yet. Each needs something Uncloud cannot ship for you:
          </p>
          <div className="flex flex-col gap-2">
            {planned.map((integration) => (
              <div key={integration.id} className="px-3 py-2">
                <div className="text-xs text-[var(--text-dim)]">{integration.name}</div>
                <p className="text-[11px] text-[var(--text-faint)] mt-0.5 leading-relaxed">
                  {integration.needs}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {state.credentials.some((c) => !c.secure) && (
        <p className="text-[11px] text-amber-400 mt-3 flex items-center gap-1.5">
          <Check size={12} /> Some credentials are stored in a file rather than the
          keychain.
        </p>
      )}
    </section>
  );
}
