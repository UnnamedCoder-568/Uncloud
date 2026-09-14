/**
 * Devices on this network: turning it on, pairing, and taking it away again.
 *
 * On the computer this is where the switch lives, because being reachable is
 * a decision about the computer — the engine is restarted with it, which is
 * why the window reloads. On a paired phone the same section lists the same
 * devices and lets that phone sign itself out; it has no switch, since a
 * device that can turn network access off from the network has just locked
 * itself out.
 */

import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, MonitorSmartphone, X } from 'lucide-react';
import QrCode from './QrCode';
import { inDesktop } from '../lib/platform';
import {
  lanDevices, lanOffer, networkAccess, renameDevice, revokeDevice, setNetworkAccess,
  signOutDevice,
} from '../lib/sidecar';
import type { LanDevices, LanOffer } from '../lib/sidecar';

function ago(seconds: number): string {
  const delta = Date.now() / 1000 - seconds;
  if (delta < 90) return 'just now';
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

export default function DevicesSection() {
  const desktop = inDesktop();
  const [enabled, setEnabled] = useState<boolean | null>(desktop ? null : true);
  const [info, setInfo] = useState<LanDevices | null>(null);
  const [offer, setOffer] = useState<LanOffer | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; label: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const refresh = useCallback(() => {
    lanDevices().then(setInfo).catch(() => setInfo(null));
  }, []);

  useEffect(() => {
    if (desktop) networkAccess().then(setEnabled).catch(() => setEnabled(false));
    refresh();
  }, [desktop, refresh]);

  // Ticks only while a code is on screen, so the countdown is honest.
  useEffect(() => {
    if (!offer) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [offer]);

  const remaining = offer ? Math.max(0, Math.round(offer.expires - now / 1000)) : 0;

  async function act(key: string, work: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try { await work(); } catch (e) { setError(String(e)); } finally { setBusy(null); }
  }

  async function toggle() {
    await act('toggle', async () => {
      await setNetworkAccess(!enabled);
      // New port, new token: nothing cached in this window is valid any more.
      window.location.reload();
    });
  }

  function armed(key: string): boolean {
    if (confirm === key) return true;
    setConfirm(key);
    setTimeout(() => setConfirm((c) => (c === key ? null : c)), 4000);
    return false;
  }

  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm mb-1 flex items-center gap-2">
            <MonitorSmartphone size={14} className="text-[var(--text-dim)]" />
            {desktop ? 'Available on this network' : 'Paired devices'}
          </h2>
          <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
            {desktop
              ? 'Use Uncloud from a phone or another computer on the same Wi-Fi. Nothing leaves the local network — there is no relay and no account, and every device has to be paired here first.'
              : 'Everything paired with the computer running Uncloud. Pairing new devices and turning network access off happen on that computer.'}
          </p>
        </div>
        {desktop && enabled !== null && (
          <button
            onClick={toggle}
            disabled={busy === 'toggle'}
            aria-label={enabled ? 'Turn off network access' : 'Turn on network access'}
            className={`w-11 h-6 rounded-full shrink-0 transition relative disabled:opacity-50 ${enabled ? 'accent-bar' : 'bg-[var(--border)]'}`}
          >
            <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition ${enabled ? 'left-5' : 'left-0.5'}`} />
          </button>
        )}
      </div>

      {busy === 'toggle' && (
        <p className="mt-3 text-[11px] text-[var(--text-faint)] flex items-center gap-1.5">
          <Loader2 size={11} className="animate-spin" /> Restarting the engine…
        </p>
      )}

      {desktop && enabled && !info && busy !== 'toggle' && (
        <p className="mt-3 text-[11px] text-amber-400/80">
          Turned on, but the engine is not answering on the network yet. Restart Uncloud if this persists.
        </p>
      )}

      {info && (
        <div className="mt-4 flex flex-col gap-4">
          {desktop && (
            <div className="flex flex-col gap-3">
              {info.addresses.length === 0 ? (
                <p className="text-[11px] text-amber-400/80">
                  No network address was found. Connect to Wi-Fi or ethernet, then turn this off and on.
                </p>
              ) : !offer || remaining === 0 ? (
                <button
                  onClick={() => act('offer', async () => { setOffer(await lanOffer()); setNow(Date.now()); })}
                  disabled={busy === 'offer'}
                  className="self-start btn-accent text-xs px-3 py-1.5 rounded-lg flex items-center gap-1.5 disabled:opacity-50"
                >
                  {busy === 'offer' && <Loader2 size={12} className="animate-spin" />}
                  {offer ? 'Code expired — show a new one' : 'Pair a device'}
                </button>
              ) : (
                <div className="flex flex-col gap-3">
                  {offer.reaches.length > 1 && (
                    <p className="text-[11px] text-[var(--text-faint)]">
                      This computer has {offer.reaches.length} addresses. Scan the one on the same network as the device.
                    </p>
                  )}
                  <div className="flex flex-wrap gap-4">
                    {offer.reaches.map((reach) => (
                      <figure key={reach.url} className="flex flex-col items-center gap-2">
                        <QrCode matrix={reach.qr} label={`Pairing code for ${reach.label}`} />
                        <figcaption className="text-[10px] text-[var(--text-faint)] text-center max-w-[196px]">
                          {reach.label}
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-faint)]">Or open the address on the device and type</div>
                    <div className="font-mono text-xl tracking-[0.12em] mt-1">{offer.code}</div>
                    <div className="text-[11px] text-[var(--text-faint)] mt-1 tabular-nums">
                      Single use · expires in {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')}
                    </div>
                  </div>
                  <button onClick={() => { setOffer(null); refresh(); }}
                          className="self-start text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition">
                    Done
                  </button>
                </div>
              )}
              <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
                The first time, a device warns that the connection is not private: the
                certificate comes from this computer, not a public authority. The connection
                is still encrypted. The pairing page offers the certificate to install; check
                its fingerprint matches <span className="font-mono break-all">{info.fingerprint}</span>.
              </p>
            </div>
          )}

          <div className="flex flex-col gap-1">
            {info.devices.length === 0 && (
              <p className="text-[11px] text-[var(--text-faint)]">No devices paired yet.</p>
            )}
            {info.devices.map((d) => (
              <div key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 border-t border-[var(--border-soft)] first:border-t-0">
                <div className="min-w-0 flex-1">
                  {renaming?.id === d.id ? (
                    <form className="flex items-center gap-1"
                          onSubmit={(e) => { e.preventDefault(); void act(`rename-${d.id}`, async () => { await renameDevice(d.id, renaming.label); setRenaming(null); refresh(); }); }}>
                      <input autoFocus value={renaming.label} maxLength={60}
                             onChange={(e) => setRenaming({ id: d.id, label: e.target.value })}
                             className="input text-xs py-1" aria-label="Device name" />
                      <button type="submit" className="tb-btn" aria-label="Save name"><Check size={13} /></button>
                      <button type="button" className="tb-btn" aria-label="Cancel" onClick={() => setRenaming(null)}><X size={13} /></button>
                    </form>
                  ) : (
                    <button onClick={() => setRenaming({ id: d.id, label: d.label })}
                            className="text-sm text-left truncate max-w-full hover:underline max-md:min-h-11"
                            title="Rename">
                      {d.label}
                      {d.current && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-inset)] text-[var(--text-faint)]">This device</span>}
                    </button>
                  )}
                  <div className="text-[11px] text-[var(--text-faint)]">
                    {d.agent} · paired {new Date(d.created * 1000).toLocaleDateString()} · seen {ago(d.last_seen)}
                  </div>
                </div>
                {d.current ? (
                  <button
                    onClick={() => act('signout', async () => { await signOutDevice(); window.location.assign('/pair'); })}
                    className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] text-[var(--text-dim)] hover:text-white transition max-md:min-h-11">
                    Sign out
                  </button>
                ) : (
                  <button
                    onClick={() => { if (armed(d.id)) void act(`revoke-${d.id}`, async () => { await revokeDevice(d.id); refresh(); }); }}
                    className={`text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-inset)] transition max-md:min-h-11 ${confirm === d.id ? 'text-rose-400' : 'text-[var(--text-dim)] hover:text-rose-400'}`}>
                    {confirm === d.id ? 'Revoke for good?' : 'Revoke'}
                  </button>
                )}
              </div>
            ))}
            {desktop && info.devices.length > 1 && (
              <button
                onClick={() => { if (armed('all')) void act('revoke-all', async () => { await revokeDevice('all'); refresh(); }); }}
                className={`self-start mt-2 text-[11px] transition ${confirm === 'all' ? 'text-rose-400' : 'text-[var(--text-faint)] hover:text-rose-400'}`}>
                {confirm === 'all' ? `Revoke all ${info.devices.length}? Every device will need pairing again.` : 'Revoke all devices'}
              </button>
            )}
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-[11px] text-rose-400">{error}</p>}
    </section>
  );
}
