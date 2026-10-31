// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ImageEnhancer from './ImageEnhancer';
import { enhanceImage, fetchImageBlobUrl, getImageJob, imageEnhancementInfo, stopImage } from '../lib/sidecar';
import type { ImageJob } from '../lib/sidecar';

vi.mock('../lib/sidecar', () => ({ enhanceImage: vi.fn(), fetchImageBlobUrl: vi.fn(),
  getImageJob: vi.fn(), imageEnhancementInfo: vi.fn(), stopImage: vi.fn() }));
vi.mock('./SaveActions', () => ({ default: () => <span>Save enhanced copy</span> }));

const pending: ImageJob = { id: 'copy', prompt: '', status: 'pending', step: 0,
  total_steps: 0, done: false, error: null, kind: 'upscale', label: null, output_path: null };
const done: ImageJob = { ...pending, done: true, status: 'done',
  elapsed_seconds: 7, output_path: '/outputs/copy-2x.png' };

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('URL', { createObjectURL: vi.fn(), revokeObjectURL: vi.fn() });
  localStorage.clear();
  vi.mocked(imageEnhancementInfo).mockResolvedValue({ ready: false, name: '2×', size_bytes: 67061725 });
  vi.mocked(enhanceImage).mockResolvedValue(pending);
  vi.mocked(getImageJob).mockResolvedValue(done);
  vi.mocked(fetchImageBlobUrl).mockResolvedValue('blob:enhanced');
});
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals(); document.body.innerHTML = ''; });

it('downloads only after a click, keeps the original selectable and releases the private preview', async () => {
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host), onView = vi.fn();
  await act(() => root.render(<ImageEnhancer sourcePath="/outputs/original.png" onView={onView} />));
  expect(enhanceImage).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Download 64 MB');
  await act(() => host.querySelector<HTMLButtonElement>('button')!.click());
  expect(enhanceImage).toHaveBeenCalledExactlyOnceWith('/outputs/original.png', true);
  expect(host.textContent).toContain('Original preserved · 7s');
  const buttons = host.querySelectorAll<HTMLButtonElement>('button');
  await act(() => buttons[1].click());
  expect(onView).toHaveBeenLastCalledWith({ src: 'blob:enhanced', name: 'copy-2x.png' });
  await act(() => buttons[0].click());
  expect(onView).toHaveBeenLastCalledWith(null);
  await act(() => root.unmount());
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:enhanced');
});

it('shows a failure without replacing the original or claiming success', async () => {
  vi.mocked(enhanceImage).mockRejectedValue(new Error('Download interrupted'));
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host), onView = vi.fn();
  await act(() => root.render(<ImageEnhancer sourcePath="/outputs/original.png" onView={onView} />));
  await act(() => host.querySelector<HTMLButtonElement>('button')!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('Download interrupted');
  expect(onView).not.toHaveBeenCalled();
  expect(fetchImageBlobUrl).not.toHaveBeenCalled();
  await act(() => root.unmount());
});

it('closing the viewer leaves a queued enhancement running', async () => {
  vi.mocked(getImageJob).mockResolvedValue({ ...pending, status: 'running', phase: 'Enhancing' });
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  await act(() => root.render(<ImageEnhancer sourcePath="/outputs/original.png" onView={() => undefined} />));
  await act(() => host.querySelector<HTMLButtonElement>('button')!.click());
  expect(host.textContent).toContain('Stop enhancement');
  await act(() => root.unmount());
  expect(stopImage).not.toHaveBeenCalled();
  expect(JSON.parse(localStorage.getItem('uncloud.image.enhancement:/outputs/original.png')!)).toEqual(['copy']);
});
