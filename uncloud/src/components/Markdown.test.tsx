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

  it('renders a colored local chart from a numeric table and returns to the original data', async () => {
    await render('| Model | Score | Change |\n|---|---|---|\n| Alpha | 9.5 | -2 |\n| Beta | 7.5 | 0 |');
    await act(() => container.querySelector<HTMLButtonElement>('[aria-label="Show bar chart"]')!.click());
    expect(container.querySelector('svg[role="img"]')?.getAttribute('aria-label')).toBe('Score by Model');
    const bars = [...container.querySelectorAll('svg[role="img"] rect')];
    expect(bars).toHaveLength(2);
    expect(bars[0].getAttribute('fill')).not.toBe(bars[1].getAttribute('fill'));
    expect(bars.every(bar => Number.isFinite(Number(bar.getAttribute('width'))))).toBe(true);
    await act(() => {
      const select = container.querySelector<HTMLSelectElement>('[aria-label="Chart metric"]')!;
      select.value = '2';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(container.querySelector('svg[role="img"]')?.getAttribute('aria-label')).toBe('Change by Model');
    expect(container.querySelector('svg[role="img"]')?.textContent).toContain('-2');
    await act(() => container.querySelector<HTMLButtonElement>('[aria-label="Show table"]')!.click());
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(container.querySelectorAll('tbody td')[1].textContent).toBe('9.5');
  });

  it('keeps generated Python as code and waits for valid numeric table rows', async () => {
    await render('```python\nimport matplotlib.pyplot as plt\nplt.show()\n```');
    expect(container.querySelector('[aria-label="Show bar chart"]')).toBeNull();
    expect(container.querySelector('pre')?.textContent).toContain('plt.show()');
    await render('| Model | Score |\n|---|---|\n| A | 9 |');
    expect(container.querySelector('[aria-label="Show bar chart"]')).toBeNull();
    await render('| Model | Score |\n|---|---|\n| A | 9 |\n| B | 8 |');
    expect(container.querySelector('[aria-label="Show bar chart"]')).not.toBeNull();
  });

  it('displays a completed chart artifact directly and keeps invalid or incomplete data as code', async () => {
    const chart = '{"title":"Sample data","labels":["A","B"],"values":[12,8]}';
    await render(`\`\`\`bar-chart\n${chart}`);
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    await render(`\`\`\`bar-chart\n${chart}\n\`\`\``);
    expect(container.querySelector('svg[role="img"]')).not.toBeNull();
    expect(container.querySelectorAll('svg[role="img"] rect')).toHaveLength(2);
    await render('```bar-chart\n{"labels":["A"],"values":[1],"script":"alert(1)"}\n```');
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(container.querySelector('pre')?.textContent).toContain('alert(1)');
  });
});
