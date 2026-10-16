import type { DeploymentPlan } from '../lib/sidecar';
import { formatBytes } from '../lib/format';

export default function DeploymentSummary({ plan, installed = false, current = '' }: {
  plan?: DeploymentPlan | null; installed?: boolean; current?: string;
}) {
  if (!plan) return <p className="text-xs text-[var(--text-faint)]">Download sizes are unavailable for this platform. Python, runtimes and model files use additional space.</p>;
  const low = plan.available_bytes !== null && plan.available_bytes < plan.recommended_free_bytes;
  return <section aria-label="Deployment size and storage" className="card p-4 flex flex-col gap-3 mt-5">
    <h2 className="text-sm font-medium">Deployment manifest</h2>
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
      <dt className="text-[var(--text-dim)]">Locked package downloads</dt>
      <dd className="text-right tabular-nums">{formatBytes(plan.download_bytes)}{plan.unknown_sizes ? ' + unlisted sizes' : ''}</dd>
      <dt className="text-[var(--text-dim)]">Packages to set up</dt><dd className="text-right tabular-nums">{plan.package_count}</dd>
      <dt className="text-[var(--text-dim)]">Recommended free space · estimate</dt>
      <dd className="text-right tabular-nums">{formatBytes(plan.recommended_free_bytes)}</dd>
      <dt className="text-[var(--text-dim)]">Available on installation drive</dt>
      <dd className="text-right tabular-nums">{plan.available_bytes === null ? 'Unavailable' : formatBytes(plan.available_bytes)}</dd>
    </dl>
    <p className="text-xs text-[var(--text-faint)]">{installed ? 'The engine is already installed; launch does not download these packages again. ' : ''}Archive sizes come from this build’s dependency lock. Cached packages reduce downloads. The space estimate allows for expansion, cache and build files; it is not an exact installed size.</p>
    <p className="text-xs text-[var(--text-faint)]">{plan.unknown_sizes ? `${plan.unknown_sizes} package size is not listed. ` : ''}Python, source-build dependencies, model weights and optional engines can require additional downloads. Models are separate from this manifest.</p>
    {low && !installed && <p role="status" className="text-xs text-amber-400">This drive has less free space than the recommended reserve.</p>}
    {current && <p role="status" className="text-xs break-words">{current}</p>}
    <details className="text-xs text-[var(--text-dim)]">
      <summary className="cursor-pointer">Package files and download sizes</summary>
      <div className="max-h-48 overflow-y-auto mt-2 flex flex-col gap-2">
        {plan.files.map(file => <div key={file.name} className="flex justify-between gap-3">
          <span className="min-w-0 break-all" title={file.file}>{file.name} {file.version}{file.kind === 'source' ? ' · source build' : ''}</span>
          <span className="shrink-0 tabular-nums">{file.bytes === null ? 'Not listed' : formatBytes(file.bytes)}</span>
        </div>)}
      </div>
    </details>
  </section>;
}
