// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import DeploymentSummary from './DeploymentSummary';
import type { DeploymentPlan } from '../lib/sidecar';

it('distinguishes known archive bytes, unknown sizes, disk reserve and an existing install', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const plan: DeploymentPlan = { platform: 'test', download_bytes: 1024, recommended_free_bytes: 4096,
    available_bytes: 2048, unknown_sizes: 1, source_builds: 0, package_count: 2,
    files: [{ name: 'known', version: '1', file: 'known.whl', bytes: 1024, kind: 'wheel' },
      { name: 'unlisted', version: '1', file: 'unlisted.whl', bytes: null, kind: 'wheel' }] };
  try {
    await act(() => root.render(<DeploymentSummary plan={plan} />));
    expect(container.textContent).toContain('+ unlisted sizes');
    expect(container.textContent).toContain('Not listed');
    expect(container.textContent).toContain('less free space');
    expect(container.textContent).toContain('not an exact installed size');
    await act(() => root.render(<DeploymentSummary plan={{ ...plan, available_bytes: null }} installed />));
    expect(container.textContent).toContain('launch does not download these packages again');
    expect(container.textContent).toContain('Unavailable');
    expect(container.textContent).not.toContain('less free space');
  } finally {
    await act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
