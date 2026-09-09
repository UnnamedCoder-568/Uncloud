/** Asking a person whether something may happen.
 *
 *  This is the surface the whole permission layer exists for. Everything below
 *  it — the gate, the risk categories, the audit log — was unreachable until
 *  there was somewhere to answer, and an engine that returns 428 to a client
 *  that ignores it is a system that fails every gated action.
 *
 *  Three things it is careful about.
 *
 *  **It says what would happen, not what was called.** `fs_write` is not a
 *  decision anybody can make; writing to a named path is.
 *
 *  **"Always" is offered only where always is possible.** Shell and delete ask
 *  every time and cannot be granted for a session — that is deliberate and not
 *  a setting — so the button is absent rather than present and ineffective.
 *
 *  **Closing it is a no.** There is no dismissal that leaves the request
 *  hanging, because a prompt that can be escaped without answering becomes a
 *  way to make the application appear stuck.
 */

import { useEffect, useState } from 'react';
import { AlertTriangle, Ban, Check, ShieldQuestion, Terminal, Trash2 } from 'lucide-react';

import { setApprovalAsker, type ApprovalAnswer, type ApprovalRequest }
  from '../lib/sidecar';

/** What each category means in a sentence, for somebody who did not write it. */
const MEANING: Record<string, string> = {
  read: 'Reading a file on this computer.',
  write: 'Writing to a file on this computer.',
  delete: 'Deleting something. This may not be undoable.',
  shell: 'Running a command with your own account’s access.',
  network: 'Reaching something over the internet.',
  install: 'Installing software or downloading a model.',
  settings: 'Changing how Uncloud itself behaves.',
  generate: 'Generating something with a model.',
  train: 'Training a model on data you have chosen.',
  device: 'Controlling something on this machine outside Uncloud.',
  message: 'Sending something to somebody else.',
};

/** Categories that never take a standing yes. Kept in step with the engine,
 *  which clamps them regardless — this only decides whether to offer a button
 *  that would not work. */
const ALWAYS_ASKS = new Set(['shell', 'delete']);

function icon(category: string) {
  if (category === 'shell') return <Terminal size={16} />;
  if (category === 'delete') return <Trash2 size={16} />;
  return <ShieldQuestion size={16} />;
}

export default function ApprovalPrompt() {
  const [pending, setPending] = useState<
    { request: ApprovalRequest; settle: (answer: ApprovalAnswer) => void } | null>(null);

  useEffect(() => {
    setApprovalAsker((request) => new Promise<ApprovalAnswer>((resolve) => {
      setPending({ request, settle: (answer) => { setPending(null); resolve(answer); } });
    }));
    return () => setApprovalAsker(null);
  }, []);

  if (!pending) return null;
  const { request, settle } = pending;
  const canAlways = !ALWAYS_ASKS.has(request.category);
  const preview = Object.entries(request.preview ?? {})
    .filter(([, value]) => value !== '' && value != null);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-8
                    bg-black/60 backdrop-blur-sm"
         // Clicking away is a no, not a dismissal. A prompt that can be escaped
         // without answering leaves the caller waiting forever.
         onClick={() => settle('no')}>
      <div className="card w-full max-w-lg flex flex-col gap-4 p-5"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3">
          <span className="text-[var(--accent)] mt-0.5">{icon(request.category)}</span>
          <div className="min-w-0">
            <h3 className="text-sm">{request.summary || request.action}</h3>
            <p className="text-[11px] text-[var(--text-faint)] mt-1">
              {MEANING[request.category] ?? request.category}
              {request.origin ? ` · asked by ${request.origin}` : ''}
            </p>
          </div>
        </div>

        {preview.length > 0 && (
          <div className="rounded-lg bg-[var(--bg-inset)] px-3 py-2 flex flex-col gap-1">
            {preview.map(([key, value]) => (
              <div key={key} className="text-[11px] font-mono break-all">
                <span className="text-[var(--text-faint)]">{key}: </span>
                <span>{String(value).slice(0, 500)}</span>
              </div>
            ))}
          </div>
        )}

        {ALWAYS_ASKS.has(request.category) && (
          <p className="text-[11px] text-amber-400 flex items-start gap-2">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            Uncloud asks every time for this, and that cannot be turned off.
          </p>
        )}

        <div className="flex items-center justify-between gap-2 pt-1">
          <button onClick={() => settle('never')}
                  className="flex items-center gap-1.5 text-[11px] px-3 py-2
                             rounded-lg text-[var(--text-faint)]
                             hover:text-rose-400 transition">
            <Ban size={12} /> Never
          </button>
          <div className="flex items-center gap-2">
            <button onClick={() => settle('no')}
                    className="text-xs px-4 py-2 rounded-lg text-[var(--text-dim)]
                               hover:text-[var(--text)] transition">
              Not now
            </button>
            {canAlways && (
              <button onClick={() => settle('always')}
                      className="text-xs px-4 py-2 rounded-lg
                                 text-[var(--text-dim)] hover:text-[var(--text)]
                                 transition">
                Always
              </button>
            )}
            <button onClick={() => settle('yes')}
                    className="flex items-center gap-1.5 text-xs px-4 py-2
                               rounded-lg btn-accent transition">
              <Check size={13} /> Allow
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
