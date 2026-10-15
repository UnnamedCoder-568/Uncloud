// @vitest-environment happy-dom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Markdown from './Markdown';

describe('streaming Markdown in the chat UI', () => {
  let container: HTMLDivElement;
  let root: Root;
  const partial = '```python\ndef sq';
  const complete = '```python\ndef square(x):\n    return x * x\n```';
  const code = 'def square(x):\n    return x * x';
  const render = (text: string) => act(() => root.render(<Markdown>{text}</Markdown>));

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('updates the same code block as more model text arrives', async () => {
    await render(partial);
    const element = container.querySelector('pre code');
    expect(element?.textContent).toBe('def sq');
    await render(complete);
    expect(container.querySelector('pre code')).toBe(element);
    expect(element?.textContent).toBe(code);
  });

  it('copies the completed streamed code rather than its first chunk', async () => {
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
    await render(partial);
    await render(complete);
    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[title="Copy"]')!.click();
    });
    expect(write).toHaveBeenCalledWith(code);
  });

  it('keeps an explicitly edited working copy when generation continues', async () => {
    await render(partial);
    await act(() => container.querySelector<HTMLButtonElement>('button[title="Edit a working copy"]')!.click());
    const editor = container.querySelector('textarea')!;
    await act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
      set.call(editor, 'my edited code');
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await render(complete);
    expect(editor.value).toBe('my edited code');
    await act(() => container.querySelector<HTMLButtonElement>('button[title="Close editor"]')!.click());
    expect(container.querySelector('pre code')?.textContent).toBe('my edited code');
  });

  it('updates a streamed table without duplicating existing rows', async () => {
    const header = '| Feature | Value |\n| --- | --- |\n';
    await render(header + '| Context | Model-specific |');
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1);
    await render(header + '| Context | Model-specific |\n| Output | Native stream |');
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(container.querySelectorAll('tbody td')[3].textContent).toBe('Native stream');
  });
});
