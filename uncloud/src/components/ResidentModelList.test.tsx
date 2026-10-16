// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import ResidentModelList from './ResidentModelList';
import type { ResidentModels } from '../lib/sidecar';

it('lists simultaneous cached models across modules and Windows path names', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  const resident: ResidentModels = {
    anything: true, text_model: 'C:\\Models\\qwen.gguf', image_pipeline: null,
    mflux_model: null, flux2_profile: null, video_pipeline: null,
    speech_workers: 1, music_jobs: 0, narration_jobs: 0,
    models: [
      { kind: 'Chat', path: 'C:\\Models\\qwen.gguf', device: 'Vulkan0: GPU', context_limit: 98304 },
      { kind: 'Transcription', path: '/models/whisper' },
      { kind: 'Text to voice', path: '/models/kokoro' },
      { kind: 'Narration', path: '/models/narrator' },
    ],
  };
  await act(() => root.render(<ResidentModelList resident={resident} />));
  expect([...container.querySelectorAll('li')].map(row => row.textContent)).toEqual([
    expect.stringContaining('qwen.gguf'), expect.stringContaining('whisper'),
    expect.stringContaining('kokoro'), expect.stringContaining('narrator'),
    'Voice: 1 active workers',
  ]);
  expect(container.textContent).toContain('Vulkan0: GPU');
  expect(container.querySelector('li')?.title).toBe('C:\\Models\\qwen.gguf');
  await act(() => root.unmount());
  vi.unstubAllGlobals();
});
