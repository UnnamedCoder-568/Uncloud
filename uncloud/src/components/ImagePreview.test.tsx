// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import ImagePreview from './ImagePreview';
import Panes from './Panes';

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ''; });

it('opens in-app, zooms, closes with Escape and restores keyboard focus', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  await act(() => root.render(<ImagePreview src="blob:private-image" alt="Sample output" name="sample.png" />));
  const trigger = host.querySelector<HTMLButtonElement>('button')!;
  trigger.focus();
  await act(() => trigger.click());
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(dialog.querySelector('img')!.src).toBe('blob:private-image');
  expect(document.activeElement?.getAttribute('aria-label')).toBe('Close image');
  expect(dialog.querySelector('a')?.download).toBe('sample.png');
  await act(() => dialog.querySelector<HTMLButtonElement>('[aria-label="Zoom in"]')!.click());
  expect(dialog.textContent).toContain('150%');
  await act(() => dialog.querySelector<HTMLButtonElement>('[aria-label="Fit image"]')!.click());
  expect(dialog.textContent).toContain('Fit');
  await act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await act(() => root.unmount());
});

it('does not leave a modal over another workspace or reopen it on return', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const panes = [{ id: 'image', render: () => <ImagePreview src="blob:output" alt="Output" /> },
    { id: 'other', render: () => <p>Other workspace</p> }];
  await act(() => root.render(<Panes active="image" panes={panes} />));
  await act(() => host.querySelector<HTMLButtonElement>('button')!.click());
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  await act(() => root.render(<Panes active="other" panes={panes} />));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await act(() => root.render(<Panes active="image" panes={panes} />));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await act(() => root.unmount());
});
