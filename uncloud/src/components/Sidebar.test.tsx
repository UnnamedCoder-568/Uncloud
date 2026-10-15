// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import Sidebar from './Sidebar';
import { resolveView } from '../lib/workspaces';

it('keeps old notification links working after merging workspaces', () => {
  expect(resolveView('friday')).toBe('jarviz');
  expect(resolveView('voice')).toBe('jarviz');
  expect(resolveView('recipes')).toBe('automations');
  expect(resolveView('personas')).toBe('personas');
  expect(resolveView('https://example.org')).toBeNull();
});

it('shows the merged destinations once and preserves other navigation', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  const change = vi.fn();
  await act(() => root.render(<Sidebar active="jarviz" onChange={change} top={null} />));
  const titles = [...container.querySelectorAll('button')].map(b => b.title);
  expect(titles.filter(t => t === 'Jarviz')).toHaveLength(1);
  expect(titles).toContain('Personas');
  expect(titles).toContain('Automations');
  expect(titles).not.toContain('Voice');
  expect(titles).not.toContain('Friday');
  expect(titles).not.toContain('Recipes');
  await act(() => container.querySelector<HTMLButtonElement>('button[title="Personas"]')!.click());
  expect(change).toHaveBeenCalledWith('personas');
  await act(() => root.unmount());
  vi.unstubAllGlobals();
});
