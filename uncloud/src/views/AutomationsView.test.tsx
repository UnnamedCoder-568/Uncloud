// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import AutomationsView from './AutomationsView';
vi.mock('../components/AutomationsPanel', () => ({ default: () => <p>Saved schedules</p> }));
vi.mock('./RecipesView', () => ({ default: () => <input aria-label="Recipe draft" defaultValue="" /> }));

it('keeps recipes and schedules together without losing an unfinished recipe', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  await act(() => root.render(<AutomationsView />));
  const tab = (name: string) => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(t => t.textContent === name)!;
  expect(container.textContent).toContain('Saved schedules');
  await act(() => tab('Recipes').click());
  const draft = container.querySelector<HTMLInputElement>('input')!;
  draft.value = 'My reusable workflow';
  await act(() => tab('Agents & schedules').click());
  await act(() => tab('Recipes').click());
  expect(container.querySelector('input')?.value).toBe('My reusable workflow');
  expect(tab('Recipes').getAttribute('aria-selected')).toBe('true');
  await act(() => root.unmount());
  vi.unstubAllGlobals();
});
