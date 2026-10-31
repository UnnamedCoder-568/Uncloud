// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import AutoImageEnhancement from './AutoImageEnhancement';
import ImagePreview from './ImagePreview';
import { fetchImageBlobUrl, enhanceImage } from '../lib/sidecar';
import type { ImageJob } from '../lib/sidecar';

vi.mock('../lib/sidecar', () => ({ fetchImageBlobUrl: vi.fn(), enhanceImage: vi.fn() }));
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); document.body.innerHTML = ''; });

it('defaults on and shares an opt-out between image workspaces and reloads', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  await act(() => root.render(<><AutoImageEnhancement /><AutoImageEnhancement /></>));
  let inputs = host.querySelectorAll<HTMLInputElement>('input');
  expect([...inputs].every(input => input.checked)).toBe(true);
  await act(() => inputs[0].click());
  expect([...inputs].every(input => !input.checked)).toBe(true);
  await act(() => root.render(<AutoImageEnhancement key="reloaded" />));
  inputs = host.querySelectorAll<HTMLInputElement>('input');
  expect(inputs[0].checked).toBe(false);
  await act(() => root.unmount());
});

it('shows the enhanced result first and compares the authenticated original without enhancing twice', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('URL', { revokeObjectURL: vi.fn() });
  vi.mocked(fetchImageBlobUrl).mockResolvedValue('blob:original');
  const job: ImageJob = { id: 'auto', prompt: 'Teapot', status: 'done', done: true,
    step: 1, total_steps: 1, error: null, kind: 'generate', label: null,
    enhanced: true, output_path: '/outputs/auto-2x.png', original_path: '/outputs/auto.png' };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  await act(() => root.render(<ImagePreview src="blob:enhanced" alt="Teapot" job={job} name="auto-2x.png" sourcePath={job.output_path!} />));
  await act(() => host.querySelector<HTMLButtonElement>('button')!.click());
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(dialog.querySelector('img')!.src).toBe('blob:enhanced');
  expect(fetchImageBlobUrl).toHaveBeenCalledExactlyOnceWith('auto', true);
  const button = (text: string) => [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === text)!;
  await act(() => button('Original').click());
  expect(dialog.querySelector('img')!.src).toBe('blob:original');
  expect(dialog.querySelector('a')!.download).toBe('auto.png');
  await act(() => button('Enhanced 2×').click());
  expect(dialog.querySelector('img')!.src).toBe('blob:enhanced');
  expect(enhanceImage).not.toHaveBeenCalled();
  await act(() => root.unmount());
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:original');
});
