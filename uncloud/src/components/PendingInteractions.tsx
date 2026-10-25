import { useState } from 'react';
import { ShieldQuestion } from 'lucide-react';
import { useInteractions } from '../lib/interactions';
import type { Interaction } from '../lib/interactions';

export function InteractionCard({ request }: { request: Interaction }) {
  const { submitting, respond } = useInteractions();
  const [answer, setAnswer] = useState('');
  const permission = request.kind === 'permission';
  return <section className="card p-4 flex flex-col gap-3 min-w-0" aria-label={permission ? 'Action approval' : 'Task question'}>
    <div className="flex items-center gap-2 text-sm font-medium">
      <ShieldQuestion size={16} className="shrink-0 text-[var(--accent)]" />
      <h3>{permission ? 'Permission needed' : 'Your answer is needed'}</h3>
    </div>
    <p className="text-sm break-words">{request.details.summary || request.details.question}</p>
    {permission && <details className="text-xs">
      <summary className="cursor-pointer faint">Review action details</summary>
      <dl className="mt-2 max-h-56 overflow-auto rounded-lg bg-[var(--bg-inset)] p-3 flex flex-col gap-3">
        {Object.entries(request.details.preview ?? {}).map(([key, value]) => <div key={key}>
          <dt className="faint mb-1">{key}</dt>
          <dd><pre className="whitespace-pre-wrap break-words">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre></dd>
        </div>)}
      </dl>
    </details>}
    {permission ? <div className="flex justify-end gap-2">
      <button className="pill" disabled={!!submitting} onClick={() => void respond(request, 'no')}>Deny</button>
      <button className="pill btn-accent" disabled={!!submitting} onClick={() => void respond(request, 'yes')}>
        {submitting === request.id ? 'Sending decision…' : 'Allow this action'}
      </button>
    </div> : <>
      {(request.details.options ?? []).map(option => <button className="pill text-left" key={option}
        disabled={!!submitting} onClick={() => void respond(request, option)}>{option}</button>)}
      <textarea aria-label="Your answer" className="input text-xs" rows={2} placeholder="Your answer"
        value={answer} onChange={event => setAnswer(event.target.value)} />
      <button className="pill self-end" disabled={!!submitting || !answer.trim()}
        onClick={() => void respond(request, answer)}>Reply and continue</button>
    </>}
    <span className="text-[10px] faint">Task {request.run_id.slice(0, 8)} · waiting for your response</span>
  </section>;
}

export default function PendingInteractions() {
  const { report, error } = useInteractions();
  const pending = report?.requests.filter(request => request.status === 'pending') ?? [];
  if (!pending.length && !error) return null;
  return <div className="relative z-30 max-w-[768px] mx-auto mb-3" role="region" aria-label="Pending task approvals and questions">
    <div className="max-h-[45vh] overflow-y-auto flex flex-col gap-3" aria-live="polite">
      {pending.map(request => <InteractionCard key={request.id} request={request} />)}
      {error && <p className="card p-3 text-xs text-rose-400" role="alert">{error}</p>}
    </div>
  </div>;
}
