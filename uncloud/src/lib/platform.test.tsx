// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { useAppViewport } from './platform';

afterEach(() => { vi.unstubAllGlobals(); document.documentElement.removeAttribute('style'); });
function Viewport() { useAppViewport(); return null; }

it('tracks the visible keyboard viewport and releases its listeners on unmount', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const viewport = new EventTarget() as EventTarget & { height: number; offsetTop: number };
  viewport.height = 800; viewport.offsetTop = 0;
  vi.stubGlobal('visualViewport', viewport);
  const root = createRoot(document.createElement('div'));
  await act(() => root.render(<Viewport />));
  expect(document.documentElement.style.getPropertyValue('--app-viewport-height')).toBe('800px');
  viewport.height = 390; viewport.offsetTop = 210;
  await act(() => viewport.dispatchEvent(new Event('resize')));
  expect(document.documentElement.style.getPropertyValue('--app-viewport-height')).toBe('390px');
  expect(document.documentElement.style.getPropertyValue('--app-viewport-top')).toBe('210px');
  await act(() => root.unmount());
  viewport.height = 100;
  viewport.dispatchEvent(new Event('resize'));
  expect(document.documentElement.style.getPropertyValue('--app-viewport-height')).toBe('');
});

it('leaves native desktop window geometry alone', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('__TAURI_INTERNALS__', {});
  document.documentElement.style.setProperty('--app-viewport-height', '720px');
  const root = createRoot(document.createElement('div'));
  await act(() => root.render(<Viewport />));
  expect(document.documentElement.style.getPropertyValue('--app-viewport-height')).toBe('720px');
  expect(document.documentElement.style.getPropertyValue('--app-viewport-top')).toBe('');
  await act(() => root.unmount());
});
