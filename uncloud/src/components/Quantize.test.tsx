// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Quantize from './Quantize';
import type { LocalModel } from '../lib/sidecar';

const api = vi.hoisted(() => ({
  bases: vi.fn(), source: vi.fn(), start: vi.fn(), jobs: vi.fn(),
}));
vi.mock('../lib/sidecar', () => ({
  getQuantizeBases: api.bases, getQuantizeSource: api.source,
  startQuantize: api.start, listQuantizeJobs: api.jobs, cancelQuantize: vi.fn(),
}));
vi.mock('./CapabilityGate', () => ({
  default: () => <div>Image or MLX engine setup</div>,
}));

const model: LocalModel = {
  id: 'compressed', name: 'Already compressed', category: 'text', engine: 'gguf',
  path: 'C:\\Models\\weights.gguf', size_gb: 16.8, catalog_id: null,
  tags: [], ready: true, note: null, capabilities: ['chat'],
};
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  api.bases.mockResolvedValue({ bases: [], bits: [4, 6, 8], gguf_bits: [2, 3, 4, 5, 6, 8] });
  api.source.mockResolvedValue({ quantization: 'Q4_K_M', file_type: 15,
    quantized: true, unchanged_bits: [4] });
  api.jobs.mockResolvedValue([]);
  api.start.mockResolvedValue({});
  container = document.createElement('div');
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});
async function choose(element: HTMLSelectElement, value: string) {
  await act(() => {
    element.value = value;
    element.dispatchEvent(new Event('change', { bubbles: true }));
  });
}
async function mount() {
  await act(() => root.render(<Quantize models={[model]} onBuilt={vi.fn()} />));
  await choose(container.querySelectorAll('select')[0], model.path);
}
const build = () => [...container.querySelectorAll('button')]
  .find(button => button.textContent === 'Build')!;

it('offers GGUF conversion without an Apple image engine and reads actual source precision', async () => {
  await mount();
  expect(api.source).toHaveBeenCalledWith(model.path);
  expect(container.textContent).toContain('Source precision: Q4_K_M');
  expect(container.textContent).not.toContain('Image or MLX engine setup');
  expect(container.querySelector<HTMLInputElement>('input:not([type="checkbox"])')?.value)
    .toBe('Already compressed (6-bit GGUF)');
  expect(container.textContent).toContain('Output size is reported after conversion');
  expect(container.textContent).not.toContain('~6.3 GB');
  expect([...container.querySelectorAll('select')[1].options].map(option => option.value))
    .toEqual(['2', '3', '4', '5', '6', '8']);
});

it('blocks an identical format and requires opt-in before compressing quantized weights again', async () => {
  await mount();
  const precision = container.querySelectorAll('select')[1];
  await choose(precision, '4');
  expect(build().disabled).toBe(true);
  expect(container.textContent).toContain('already the selected format');
  await choose(precision, '3');
  expect(build().disabled).toBe(true);
  await act(() => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  expect(build().disabled).toBe(false);
  await act(() => build().click());
  expect(api.start).toHaveBeenCalledWith(expect.objectContaining({
    source: model.path, kind: 'gguf', base: '', transformer_bits: 3,
    name: 'Already compressed (3-bit GGUF)', allow_requantize: true,
  }));
});

it('keeps conversion unavailable when source inspection fails', async () => {
  api.source.mockRejectedValueOnce(new Error('Choose a valid GGUF model file.'));
  await mount();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('valid GGUF');
  expect(build().disabled).toBe(true);
  expect(api.start).not.toHaveBeenCalled();
});
