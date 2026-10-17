// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import BenchmarkView from './BenchmarkView';

const mocks = vi.hoisted(() => ({ api: vi.fn(), apiPost: vi.fn() }));
vi.mock('../lib/sidecar', () => mocks);

it('runs a bounded benchmark without model loading and shows native token counts', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const runtime = { running: true, model_path: 'C:\\Models\\test.gguf', engine: 'gguf', context_limit: 65536 };
  mocks.api.mockImplementation((path: string) => Promise.resolve(path.includes('performance') ? runtime : {}));
  mocks.apiPost.mockResolvedValue({ id: 'bench', status: 'done', cursor: 0, timings: {
    first_token_ms: 400, stream_tokens_per_second: 26, usage: { prompt_tokens: 22, completion_tokens: 64 }, runtime,
  } });
  const container = document.createElement('div');
  const root = createRoot(container);
  try {
    await act(() => root.render(<BenchmarkView />));
    expect(container.textContent).toContain('test.gguf');
    const start = [...container.querySelectorAll('button')].find(b => b.textContent === 'Run short benchmark')!;
    await act(() => start.click());
    expect(mocks.apiPost).toHaveBeenCalledWith('/api/models/benchmark', {}, expect.any(AbortSignal));
    expect(container.textContent).toContain('0.40 s');
    expect(container.textContent).toContain('26.0 tokens/s');
    expect(container.textContent).toContain('22');
    expect(start.disabled).toBe(false);
    expect(mocks.api.mock.calls.every(([path]) => !String(path).includes('/engine/start'))).toBe(true);
  } finally {
    await act(() => root.unmount());
    vi.unstubAllGlobals();
  }
});
