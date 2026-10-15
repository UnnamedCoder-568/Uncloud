// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { Talk } from './VoiceToVoice';
import { streamChat } from '../lib/sidecar';
import Panes from '../components/Panes';

const talk = vi.hoisted(() => ({ active: false, toggle: vi.fn(),
  respond: null as null | ((said: string, say: (text: string) => void, signal: AbortSignal) => Promise<unknown>) }));
vi.mock('../lib/useTalk', async original => ({ ...await original<typeof import('../lib/useTalk')>(),
  useTalk: (_voice: string, respond: typeof talk.respond) => {
    talk.respond = respond;
    return { ready: true, active: talk.active, toggle: talk.toggle, native: true };
  },
}));
vi.mock('../components/ReplyVoice', () => ({ default: () => null, useSavedVoices: () => [] }));
vi.mock('../lib/sidecar', async original => ({ ...await original<typeof import('../lib/sidecar')>(),
  getLibrary: vi.fn(async () => [{ path: '/model', name: 'Test model', category: 'text', ready: true, engine: 'mlx' }]),
  engineStatus: vi.fn(async () => ({ running: true, model_path: '/model' })),
  streamChat: vi.fn(async function* () { yield { kind: 'text', text: 'Hello there.' }; }),
}));

it('sends the model only the conversation and stops listening when Jarviz is hidden', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  const render = (active: string) => root.render(<Panes active={active} panes={[
    { id: 'jarviz', render: () => <Talk /> }, { id: 'other', render: () => <p>Another workspace</p> },
  ]} />);
  await act(async () => render('jarviz'));
  await act(async () => { await talk.respond!('Hello.', vi.fn(), new AbortController().signal); });
  expect(vi.mocked(streamChat).mock.calls[0][0]).toEqual([{ role: 'user', content: 'Hello.' }]);
  talk.active = true;
  await act(() => render('other'));
  expect(talk.toggle).toHaveBeenCalledOnce();
  await act(() => root.unmount());
  vi.unstubAllGlobals();
});
