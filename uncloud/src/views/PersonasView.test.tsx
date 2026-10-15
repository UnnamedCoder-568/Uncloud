// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PersonasView from './PersonasView';
import { engineStatus, savePersona, startEngine } from '../lib/sidecar';

const profile = { id: '0123456789abcdef', name: 'Storyteller', instructions: 'Tell gentle stories.', model_path: '/model', created: 1, updated: 1 };
vi.mock('../components/CapabilityGate', () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('./ChatView', () => ({ default: ({ persona }: { persona: typeof profile }) => <p data-testid="persona-chat">{persona.instructions}</p> }));
vi.mock('../lib/sidecar', () => ({
  listPersonas: vi.fn(async () => [profile]),
  getLibrary: vi.fn(async () => [{ name: 'Local model', path: '/model', engine: 'mlx', category: 'text', ready: true }]),
  engineStatus: vi.fn(async () => ({ running: false })),
  startEngine: vi.fn(async () => ({})),
  savePersona: vi.fn(async body => ({ ...profile, ...body })),
}));

let container: HTMLDivElement;
let root: Root;
beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.clearAllMocks();
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<PersonasView />));
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
const button = (text: string) => [...container.querySelectorAll('button')].find(b => b.textContent?.includes(text))!;

it('allows editing and saving a persona without loading any model', async () => {
  expect(startEngine).not.toHaveBeenCalled();
  await act(() => button('Edit').click());
  const input = container.querySelector('textarea')!;
  await act(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, 'New exact instructions.');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => button('Save persona').click());
  expect(savePersona).toHaveBeenCalledExactlyOnceWith({ name: 'Storyteller', instructions: 'New exact instructions.', model_path: '/model' }, profile.id);
  expect(startEngine).not.toHaveBeenCalled();
});

it('loads a selected model only after the user starts a configured persona', async () => {
  expect(engineStatus).not.toHaveBeenCalled();
  await act(async () => button('Start conversation').click());
  expect(startEngine).toHaveBeenCalledExactlyOnceWith('/model', 'mlx');
  expect(container.querySelector('[data-testid="persona-chat"]')?.textContent).toBe(profile.instructions);
  await act(() => button('Personas').click());
  expect(container.querySelector('[data-testid="persona-chat"]')).toBeNull();
  expect(button('Edit')).toBeTruthy();
});
