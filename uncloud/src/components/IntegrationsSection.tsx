/** Settings → Integrations: what Uncloud can reach, and what each one needs.
 *
 *  The screen is built around six states rather than a connected boolean,
 *  because "not working" has six different remedies here and telling somebody
 *  the wrong one wastes their afternoon. The one that matters most is
 *  NOT CONFIGURED: Google and Microsoft are fully implemented and cannot work
 *  until the user registers an OAuth application with the provider. Uncloud
 *  ships no OAuth clients — they are issued to a named party under the
 *  provider's terms — so that state is honest rather than an excuse, and the
 *  remedy is spelled out.
 *
 *  Nothing here displays a secret, because nothing upstream returns one. The
 *  engine hands back a label and a state; tokens live in the keychain.
 */

import { useCallback, useEffect, useState } from 'react';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { AlertTriangle, Check, ChevronRight, FolderOpen, KeyRound, Loader2,
         Lock, Plug, Server, Settings2, X } from 'lucide-react';

import {
  addMcpServer, authorizeIntegration, configureIntegration, connectIntegration,
  connectMcpServer, disconnectIntegration, disconnectMcpServer, forgetMcpServer,
  getIntegrations, type ConnectionState, type IntegrationInfo,
  type IntegrationsState,
} from '../lib/sidecar';

const STATE_LABEL: Record<ConnectionState, string> = {
  connected: 'Connected',
  not_connected: 'Not connected',
  not_configured: 'Configuration required',
  authentication_required: 'Sign in again',
  error: 'Error',
  unavailable: 'Not available on this computer',
};

const STATE_TONE: Record<ConnectionState, string> = {
  connected: 'text-emerald-400',
  not_connected: 'text-[var(--text-faint)]',
  not_configured: 'text-amber-400',
  authentication_required: 'text-amber-400',
  error: 'text-rose-400',
  unavailable: 'text-[var(--text-faint)]',
};

export default function IntegrationsSection() {
  const [state, setState] = useState<IntegrationsState | null>(null);
  const [busy, setBusy] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getIntegrations().then(setState).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  /** Run one action, showing progress and taking the new state if it came back.
   *
   *  Several endpoints answer with the whole integration list, which saves a
   *  round trip; the rest answer with something narrower and are followed by a
   *  reload. Deciding here rather than at each call site keeps the twenty-odd
   *  buttons below down to one line each.
   */
  async function act(id: string, work: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      const next = await work();
      if (next && typeof next === 'object' && 'integrations' in next) {
        setState(next as unknown as IntegrationsState);
      } else {
        load();
      }
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy('');
    }
  }

  if (!state) return null;

  const mcp = state.integrations.filter((i) => i.id.startsWith('mcp.'));
  const providers = state.integrations.filter((i) => !i.id.startsWith('mcp.'));

  return (
    <>
      <section className="card p-4">
        <h2 className="text-sm mb-1">Integrations</h2>
        <p className="text-[11px] text-[var(--text-faint)] mb-3 leading-relaxed">
          What Uncloud can reach outside itself. Connecting something gives the
          agent no permission to use it — that is asked separately, each time it
          happens.
        </p>

        {!state.keychain && (
          <Warning>
            There is no system keychain on this computer, so credentials would be
            kept in a file readable only by you. That is weaker than a keychain,
            and worth deciding about before connecting anything.
          </Warning>
        )}
        {error && <Warning tone="rose">{error}</Warning>}

        <div className="flex flex-col gap-1.5">
          {providers.map((integration) => (
            <Row key={integration.id}
                 integration={integration}
                 busy={busy === integration.id}
                 open={expanded === integration.id}
                 onToggle={() => setExpanded(
                   expanded === integration.id ? null : integration.id)}
                 onAct={act} />
          ))}
        </div>
      </section>

      <McpSection servers={mcp} busy={busy} onAct={act} onReload={load} />
    </>
  );
}

function Warning({ children, tone = 'amber' }:
                 { children: React.ReactNode; tone?: 'amber' | 'rose' }) {
  const colour = tone === 'rose' ? 'text-rose-400' : 'text-amber-400';
  return (
    <div className={`flex items-start gap-2 text-[11px] ${colour} mb-3
                     border-l-2 border-current/40 pl-3 leading-relaxed`}>
      <AlertTriangle size={13} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function Row({ integration, busy, open, onToggle, onAct }: {
  integration: IntegrationInfo; busy: boolean; open: boolean;
  onToggle: () => void;
  onAct: (id: string, work: () => Promise<unknown>) => Promise<void>;
}) {
  const { connection } = integration;
  const state = connection.state;

  async function chooseFolder() {
    const picked = await openDialog({
      directory: true, multiple: false,
      title: `Choose a folder for ${integration.name}`,
    });
    if (typeof picked === 'string') {
      await onAct(integration.id,
                  () => connectIntegration(integration.id, { label: picked }));
    }
  }

  return (
    <div className="rounded-lg bg-[var(--bg-inset)]">
      <button onClick={onToggle}
              className="w-full flex items-start justify-between gap-3 px-3 py-2.5
                         text-left hover:brightness-110 transition">
        <span className="min-w-0">
          <span className="flex items-center gap-2">
            <Plug size={13} className="text-[var(--text-dim)]" />
            <span className="text-xs">{integration.name}</span>
            {integration.sensitivity === 'private' && (
              <span className="flex items-center gap-1 text-[10px]
                               text-[var(--text-faint)]">
                <Lock size={10} /> stays local
              </span>
            )}
          </span>
          <span className={`block text-[11px] mt-1 ${STATE_TONE[state]}`}>
            {STATE_LABEL[state]}
            {connection.account && ` · ${connection.account}`}
          </span>
        </span>
        <span className="flex items-center gap-2 shrink-0">
          {busy && <Loader2 size={13} className="animate-spin" />}
          <span className="text-[10px] text-[var(--text-faint)]">
            {integration.capabilities.length} capabilities
          </span>
          <ChevronRight size={13}
                        className={`text-[var(--text-faint)] transition
                                    ${open ? 'rotate-90' : ''}`} />
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 flex flex-col gap-3">
          <p className="text-[11px] text-[var(--text-faint)] leading-relaxed">
            {integration.summary}
          </p>

          {(state === 'not_configured' || state === 'error') && integration.needs && (
            <Warning>{integration.needs}</Warning>
          )}
          {connection.remedy && state !== 'connected' && (
            <p className="text-[11px] text-[var(--text-dim)] leading-relaxed">
              {connection.remedy}
            </p>
          )}

          {state === 'not_configured' && <ConfigureForm integration={integration}
                                                        onAct={onAct} />}
          {state === 'not_connected' && integration.auth_kind === 'token' && (
            <TokenForm integration={integration} onAct={onAct} />
          )}
          {state === 'not_connected' && integration.auth_kind === 'none' && (
            <button onClick={chooseFolder}
                    className="self-start flex items-center gap-1.5 text-[11px]
                               btn-accent px-3 py-1.5 rounded-full transition">
              <FolderOpen size={12} /> Choose folder
            </button>
          )}
          {(state === 'not_connected' || state === 'authentication_required')
            && integration.auth_kind.startsWith('oauth') && (
            <ScopeChooser integration={integration} onAct={onAct} />
          )}

          <Capabilities integration={integration} />

          {state !== 'not_connected' && state !== 'not_configured' && (
            <div className="flex items-center gap-3">
              <button
                onClick={() => onAct(integration.id,
                                     () => disconnectIntegration(integration.id))}
                className="text-[11px] text-[var(--text-faint)]
                           hover:text-rose-400 transition">
                Disconnect
              </button>
              {integration.auth_kind.startsWith('oauth') && (
                <button
                  onClick={() => onAct(integration.id,
                                       () => disconnectIntegration(integration.id, true))}
                  className="text-[11px] text-[var(--text-faint)]
                             hover:text-rose-400 transition"
                  title="Also forget the OAuth client you registered">
                  Forget configuration
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Capabilities({ integration }: { integration: IntegrationInfo }) {
  if (integration.capabilities.length === 0) return null;
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-[var(--text-faint)] mb-1">
        Capabilities
      </p>
      <div className="flex flex-wrap gap-1">
        {integration.capabilities.map((capability) => (
          <span key={capability}
                className="text-[10px] font-mono px-1.5 py-0.5 rounded
                           bg-[var(--bg)] text-[var(--text-dim)]">
            {capability}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Entering an OAuth client the user registered themselves. */
function ConfigureForm({ integration, onAct }: {
  integration: IntegrationInfo;
  onAct: (id: string, work: () => Promise<unknown>) => Promise<void>;
}) {
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');

  return (
    <div className="flex flex-col gap-2">
      <Field label="Client ID" value={clientId} onChange={setClientId}
             placeholder="from the provider's developer console" />
      <Field label="Client secret" value={clientSecret} onChange={setClientSecret}
             placeholder="only if the provider requires one" secret />
      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
        Register <span className="font-mono">http://127.0.0.1</span> as a
        desktop/native redirect. The port changes each sign-in, which is what these
        providers expect from a native application.
      </p>
      <button
        disabled={!clientId.trim()}
        onClick={() => onAct(integration.id, () => configureIntegration(
          integration.id, { client_id: clientId.trim(),
                            client_secret: clientSecret.trim() }))}
        className="self-start flex items-center gap-1.5 text-[11px] btn-accent
                   px-3 py-1.5 rounded-full transition disabled:opacity-30">
        <Settings2 size={12} /> Save configuration
      </button>
    </div>
  );
}

function TokenForm({ integration, onAct }: {
  integration: IntegrationInfo;
  onAct: (id: string, work: () => Promise<unknown>) => Promise<void>;
}) {
  const [token, setToken] = useState('');
  return (
    <div className="flex flex-col gap-2">
      {integration.needs && (
        <p className="text-[11px] text-[var(--text-dim)] leading-relaxed">
          {integration.needs}
        </p>
      )}
      <Field label="Token" value={token} onChange={setToken}
             placeholder="paste it here" secret />
      <button
        disabled={!token.trim()}
        onClick={() => onAct(integration.id, () => connectIntegration(
          integration.id, { secret: token.trim() }))}
        className="self-start flex items-center gap-1.5 text-[11px] btn-accent
                   px-3 py-1.5 rounded-full transition disabled:opacity-30">
        <KeyRound size={12} /> Connect
      </button>
    </div>
  );
}

/** Which permissions to ask the provider for.
 *
 *  Optional scopes are opt-in rather than requested wholesale: somebody who
 *  wants Uncloud to read their mail but never send it should be able to say so
 *  at the point where the provider is actually being asked.
 */
function ScopeChooser({ integration, onAct }: {
  integration: IntegrationInfo;
  onAct: (id: string, work: () => Promise<unknown>) => Promise<void>;
}) {
  const [chosen, setChosen] = useState<string[]>(
    () => integration.scopes.filter((s) => s.required).map((s) => s.id));

  function toggle(id: string) {
    setChosen((current) => current.includes(id)
      ? current.filter((s) => s !== id)
      : [...current, id]);
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[10px] uppercase tracking-wide text-[var(--text-faint)]">
        What to allow
      </p>
      {integration.scopes.map((scope) => (
        <label key={scope.id}
               className="flex items-start gap-2 text-[11px] cursor-pointer">
          <input type="checkbox" className="mt-0.5"
                 checked={chosen.includes(scope.id)}
                 disabled={scope.required}
                 onChange={() => toggle(scope.id)} />
          <span>
            {scope.summary}
            {scope.required && (
              <span className="text-[var(--text-faint)]"> · required</span>
            )}
          </span>
        </label>
      ))}
      <button
        onClick={() => onAct(integration.id,
                             () => authorizeIntegration(integration.id, chosen))}
        className="self-start flex items-center gap-1.5 text-[11px] btn-accent
                   px-3 py-1.5 rounded-full transition">
        <Check size={12} /> Sign in with {integration.name}
      </button>
      <p className="text-[10px] text-[var(--text-faint)]">
        A browser window opens. Uncloud waits for it and never sees your password.
      </p>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, secret }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; secret?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-faint)]">
        {label}
      </span>
      <input type={secret ? 'password' : 'text'} value={value}
             placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)}
             className="bg-[var(--bg)] px-3 py-2 rounded-lg text-xs outline-none
                        font-mono placeholder:text-[var(--text-faint)]" />
    </label>
  );
}

/** MCP servers, listed with the risk each tool is governed as.
 *
 *  Shown rather than hidden because it is an inference about somebody else's
 *  code. A user who disagrees should be able to see it here, not discover it
 *  by being asked at an unexpected moment.
 */
function McpSection({ servers, busy, onAct, onReload }: {
  servers: IntegrationInfo[]; busy: string;
  onAct: (id: string, work: () => Promise<unknown>) => Promise<void>;
  onReload: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ id: '', command: '', args: '' });

  return (
    <section className="card p-4">
      <div className="flex items-center justify-between gap-3 mb-1">
        <h2 className="text-sm">MCP servers</h2>
        <button onClick={() => setAdding(!adding)}
                className="text-[11px] text-[var(--text-dim)]
                           hover:text-[var(--text)] transition">
          {adding ? 'Cancel' : 'Add a server'}
        </button>
      </div>
      <p className="text-[11px] text-[var(--text-faint)] mb-3 leading-relaxed">
        Tools published by Model Context Protocol servers. They go through the
        same permissions and approvals as everything else — a server describing
        its own tool as harmless does not make it so.
      </p>

      {adding && (
        <div className="flex flex-col gap-2 mb-3 p-3 rounded-lg bg-[var(--bg-inset)]">
          <Field label="Name" value={draft.id}
                 onChange={(v) => setDraft({ ...draft, id: v })}
                 placeholder="notes" />
          <Field label="Command" value={draft.command}
                 onChange={(v) => setDraft({ ...draft, command: v })}
                 placeholder="npx" />
          <Field label="Arguments" value={draft.args}
                 onChange={(v) => setDraft({ ...draft, args: v })}
                 placeholder="-y @modelcontextprotocol/server-filesystem /path" />
          <button
            disabled={!draft.id.trim() || !draft.command.trim()}
            onClick={async () => {
              await onAct('mcp-add', () => addMcpServer({
                id: draft.id.trim(), command: draft.command.trim(),
                args: draft.args.split(' ').filter(Boolean),
                label: draft.id.trim(),
              }));
              setDraft({ id: '', command: '', args: '' });
              setAdding(false);
              onReload();
            }}
            className="self-start text-[11px] btn-accent px-3 py-1.5 rounded-full
                       transition disabled:opacity-30">
            Add
          </button>
        </div>
      )}

      {servers.length === 0 && !adding && (
        <p className="text-[11px] text-[var(--text-faint)]">
          None configured.
        </p>
      )}

      <div className="flex flex-col gap-2">
        {servers.map((server) => (
          <div key={server.id} className="rounded-lg bg-[var(--bg-inset)] p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Server size={13} className="text-[var(--text-dim)]" />
                  <span className="text-xs">{server.name}</span>
                  <span className={`text-[10px] ${
                    server.connected ? 'text-emerald-400'
                                     : 'text-[var(--text-faint)]'}`}>
                    {server.connected ? 'running' : 'stopped'}
                  </span>
                </div>
                <div className="text-[11px] text-[var(--text-faint)] mt-0.5 font-mono
                                truncate">
                  {server.mcp?.config.command} {server.mcp?.config.args.join(' ')}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {busy === server.id && <Loader2 size={12} className="animate-spin" />}
                <button
                  onClick={() => onAct(server.id, () => (
                    server.connected
                      ? disconnectMcpServer(server.mcp!.config.id)
                      : connectMcpServer(server.mcp!.config.id)))}
                  className="text-[11px] text-[var(--text-dim)]
                             hover:text-[var(--text)] transition">
                  {server.connected ? 'Stop' : 'Start'}
                </button>
                <button
                  onClick={() => onAct(server.id,
                                       () => forgetMcpServer(server.mcp!.config.id))}
                  className="text-[var(--text-faint)] hover:text-rose-400 transition">
                  <X size={13} />
                </button>
              </div>
            </div>

            {server.mcp && server.mcp.tools.length > 0 && (
              <div className="mt-2 flex flex-col gap-1">
                {server.mcp.tools.map((tool) => (
                  <div key={tool.name}
                       className="flex items-baseline justify-between gap-3 text-[11px]">
                    <span className="font-mono truncate">{tool.name}</span>
                    <span className="text-[10px] text-[var(--text-faint)] shrink-0">
                      asks as {tool.risk}
                    </span>
                  </div>
                ))}
                <p className="text-[10px] text-[var(--text-faint)] mt-1 leading-relaxed">
                  Uncloud infers how carefully to treat each tool from its name.
                  It only ever rounds up, and a tool it does not recognise is
                  treated as a write.
                </p>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
