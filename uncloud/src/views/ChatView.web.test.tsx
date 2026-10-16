// @vitest-environment happy-dom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChatView from './ChatView';
import { apiPost, countChatContext, engineStatus, startEngine, streamChat,
  uploadChatAttachment, webRead, webSearch, writeConversation } from '../lib/sidecar';

const state = vi.hoisted(() => ({ values: {} as Record<string, string> }));
vi.mock('../lib/inference', () => ({ useInference: () => ({
  info: { active: { model_path: '/test/model', profile: { capabilities: { native_tools: true } } } }, values: state.values, setValues: vi.fn(), refresh: vi.fn(),
}) }));
vi.mock('../lib/useTalk', async (original) => ({
  ...await original<typeof import('../lib/useTalk')>(),
  useTalk: () => ({ ready: false, active: false, toggle: vi.fn() }),
}));
vi.mock('../lib/printer-sound', () => ({ printerSound: {
  prepare: vi.fn(), writing: vi.fn(), stop: vi.fn(),
} }));
vi.mock('../components/InferenceControls', () => ({ default: () => null }));
vi.mock('../components/ReplyVoice', () => ({ default: () => null }));
vi.mock('../components/ActivityOrb', () => ({ default: () => null }));
vi.mock('../lib/sidecar', async (original) => ({
  ...await original<typeof import('../lib/sidecar')>(),
  apiPost: vi.fn(),
  getLibrary: vi.fn(async () => []),
  engineStatus: vi.fn(async () => ({ running: true, model_path: '/test/model', engine: 'mlx' })),
  startEngine: vi.fn(),
  getPermissions: vi.fn(async () => ({ policy: { network: 'ask_category' } })),
  listConversations: vi.fn(async () => ({ conversations: [], unreadable: 0, secure: true, backend: 'test' })),
  writeConversation: vi.fn(async () => ({})),
  countChatContext: vi.fn(async () => ({ used: 100, limit: 8192, reply_limit: 2048 })),
  streamChat: vi.fn(),
  uploadChatAttachment: vi.fn(),
  webSearch: vi.fn(async () => ({ results: 'Source https://example.org/source\nVerified test evidence.' })),
  webRead: vi.fn(async () => ({ text: 'Source https://example.org/source\nVerified test evidence.' })),
}));

describe('Web handoff through the Chat interface', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    localStorage.clear();
    localStorage.setItem('uncloud.chat.pictures', 'off');
    state.values = {};
    vi.clearAllMocks();
    vi.mocked(uploadChatAttachment).mockReset();
    vi.mocked(countChatContext).mockResolvedValue({ used: 100, limit: 8192, reply_limit: 2048, exact: true });
    vi.mocked(webSearch).mockResolvedValue({ results: 'Source https://example.org/source\nVerified test evidence.' });
    vi.mocked(webRead).mockResolvedValue({ text: 'Source https://example.org/source\nVerified test evidence.' });
    vi.mocked(apiPost).mockReset();
    vi.mocked(engineStatus).mockResolvedValue({ running: true, model_path: '/test/model', engine: 'mlx' });
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const mount = () => act(async () => root.render(<ChatView />));

  it.each(['32768', ''])('applies custom context or resets Auto for input %s', async (value) => {
    localStorage.setItem('uncloud.chat.contextWindows', JSON.stringify({ '/test/model': 16384 }));
    vi.mocked(engineStatus).mockResolvedValue({ running: true, model_path: '/test/model', engine: 'gguf',
      context_limit: 1024, context_profile: { native_limit: 131072, effective_limit: 1024,
        source: 'runtime', limited_by_memory: true } });
    vi.mocked(startEngine).mockResolvedValue({ running: true, engine: 'gguf', context_limit: 32768,
      context_profile: { native_limit: 131072, effective_limit: 32768,
        source: 'runtime', limited_by_memory: false } });
    await mount();
    expect(container.querySelector<HTMLInputElement>('#context-length')!.value).toBe('16384');
    await act(() => {
      const input = container.querySelector<HTMLInputElement>('#context-length')!;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => [...container.querySelectorAll('button')]
      .find(button => button.textContent === 'Apply context window')!.click());
    expect(startEngine).toHaveBeenCalledExactlyOnceWith('/test/model', 'gguf', null,
      value ? 32768 : undefined, true);
    expect(container.textContent).toContain('32,768 tokens');
    const saved = JSON.parse(localStorage.getItem('uncloud.chat.contextWindows')!);
    expect(saved['/test/model']).toBe(value ? 32768 : undefined);
  });
  const replies = (...answers: string[]) => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      const text = answers.shift();
      if (text === undefined) throw new Error('Unexpected extra model pass');
      const match = text.match(/^\[\[(search|read): (.*?)\]\]$/);
      if (match) yield { kind: 'tool_calls', text: '', tool_calls: [{ id: `call-${answers.length}`,
        type: 'function', function: { name: match[1] === 'search' ? 'web_search' : 'web_read',
          arguments: JSON.stringify({ [match[1] === 'search' ? 'query' : 'url']: match[2] }) } }] };
      else yield { kind: 'text', text };
    });
  };
  async function send(text: string) {
    await act(() => {
      const editor = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(editor, text);
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Send"]')!.click());
    expect(container.querySelector('button[aria-label="Stop response"]')).toBeNull();
  }

  it.each([false, true])('continues a full context and recalls originals when summarizing fails=%s', async (failure) => {
    vi.mocked(countChatContext).mockImplementation(async (turns) => ({
      used: turns.reduce((sum, turn) => sum + turn.content.length, 200),
      limit: 2000, reply_limit: 2000, exact: true,
    }));
    vi.mocked(apiPost).mockImplementation(async () => {
      if (failure) throw new Error('Compaction timed out');
      return { summary: 'Project Cedar.' };
    });
    let pass = 0;
    vi.mocked(streamChat).mockImplementation(async function* () {
      pass++;
      if (pass === 1) yield { kind: 'text', text: 'Earlier response. '.repeat(100) };
      else if (pass === 2) yield { kind: 'tool_calls', text: '', tool_calls: [{ id: 'recall-1', type: 'function',
        function: { name: 'conversation_search', arguments: JSON.stringify({ query: 'Cedar code' }) } }] };
      else if (pass === 3) yield { kind: 'text', text: 'The code was 42.' };
      else throw new Error('Unexpected extra model pass');
    });
    await mount();
    await send('The Cedar code is 42.');
    await send('What was the code?');
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(streamChat).toHaveBeenCalledTimes(3);
    expect(vi.mocked(streamChat).mock.calls[1][3]?.historyTools).toBe(true);
    const recall = vi.mocked(streamChat).mock.calls[2][0].find(turn => turn.role === 'tool');
    expect(recall?.content).toContain('The Cedar code is 42.');
    const saved = vi.mocked(writeConversation).mock.calls.at(-1)![1];
    expect(saved.messages).toHaveLength(4);
    expect(saved.messages[0].content).toBe('The Cedar code is 42.');
    expect(saved.compacted_through).toBe(2);
    expect(container.textContent).toContain('The code was 42.');
  });

  it('compacts during a multi-tool handoff and fits both results without losing call IDs', async () => {
    vi.mocked(countChatContext).mockImplementation(async turns => ({
      used: JSON.stringify(turns).length + 200, limit: 2400, reply_limit: 2400, exact: true,
    }));
    vi.mocked(apiPost).mockResolvedValue({ summary: 'Earlier context retained.' });
    vi.mocked(webSearch).mockResolvedValue({ results: `First source\nhttps://one.example/source\n${'Evidence one '.repeat(700)}` });
    vi.mocked(webRead).mockResolvedValue({ text: `Second source\nhttps://two.example/source\n${'Evidence two '.repeat(700)}` });
    let pass = 0;
    vi.mocked(streamChat).mockImplementation(async function* () {
      pass++;
      if (pass === 1) yield { kind: 'text', text: 'Earlier reply. '.repeat(35) };
      else if (pass === 2) yield { kind: 'tool_calls', text: '', tool_calls: [
        { id: 'one', type: 'function', function: { name: 'web_search', arguments: '{"query":"first source"}' } },
        { id: 'two', type: 'function', function: { name: 'web_read', arguments: '{"url":"https://two.example/source"}' } },
      ] };
      else if (pass === 3) yield { kind: 'text', text: 'Both sources compared.' };
      else throw new Error('Unexpected extra model pass');
    });
    await mount();
    await send('Some earlier context');
    await send('Compare both sources');
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(streamChat).toHaveBeenCalledTimes(3);
    const final = vi.mocked(streamChat).mock.calls[2][0];
    expect(final.filter(turn => turn.role === 'tool').map(turn => turn.tool_call_id)).toEqual(['one', 'two']);
    expect(JSON.stringify(final)).toContain('https://one.example/source');
    expect(JSON.stringify(final)).toContain('https://two.example/source');
    expect(container.textContent).toContain('Both sources compared.');
    expect(vi.mocked(writeConversation).mock.calls.at(-1)![1].messages).toHaveLength(4);
  });

  it('copies the user message verbatim without markdown or thinking cleanup', async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    replies('An answer.');
    await mount();
    const text = 'Keep **bold**, <think>literal tags</think> and\nnew lines.';
    await send(text);
    const button = container.querySelector<HTMLButtonElement>('button[aria-label="Copy message"]')!;
    expect(button.closest('.chat-message-actions-user')).not.toBeNull();
    await act(async () => button.click());
    expect(writeText).toHaveBeenCalledExactlyOnceWith(text);
    expect(button.textContent).toBe('Copied');
  });

  it('offers document attachments directly on the composer for a text model', async () => {
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
    const file = new File(['Revenue,Value\nA,12'], 'report.csv', { type: 'text/csv' });
    vi.mocked(uploadChatAttachment).mockResolvedValue({ name: 'report.csv', type: 'text/csv', text: 'Revenue,Value\nA,12', clipped: false });
    replies('The file contains a revenue table.');
    await mount();
    const attach = container.querySelector<HTMLButtonElement>('[aria-label="Attach files"]')!;
    expect(attach.closest('.composer-actions')).not.toBeNull();
    expect(attach.closest('details')).toBeNull();
    await act(() => attach.click());
    const picker = click.mock.instances.at(-1) as HTMLInputElement;
    expect(picker?.accept).toContain('.csv');
    expect(picker?.accept).not.toContain('.png');
    Object.defineProperty(picker!, 'files', { value: [file] });
    await act(async () => picker!.dispatchEvent(new Event('change')));
    expect(uploadChatAttachment).toHaveBeenCalledExactlyOnceWith(file);
    expect(container.querySelector('.composer-attachments')?.textContent).toContain('report.csv');
    await send('Read this file.');
    expect(JSON.stringify(vi.mocked(streamChat).mock.calls[0][0])).toContain('Revenue,Value');
    click.mockRestore();
  });

  it('offers image selection when the loaded runtime reports vision support', async () => {
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
    vi.mocked(engineStatus).mockResolvedValue({ running: true, model_path: '/test/model', engine: 'mlx', supports_vision: true });
    await mount();
    await act(() => container.querySelector<HTMLButtonElement>('[aria-label="Attach files or images"]')!.click());
    const picker = click.mock.instances.at(-1) as HTMLInputElement;
    expect(picker?.accept).toContain('.png');
    expect(picker?.accept).toContain('.docx');
    click.mockRestore();
  });

  it('shows one generation indicator above the input card, with no placeholder spinner', async () => {
    let finish!: () => void;
    const waiting = new Promise<void>(resolve => { finish = resolve; });
    vi.mocked(streamChat).mockImplementation(async function* () {
      await waiting;
      yield { kind: 'text', text: 'Done.' };
    });
    await mount();
    await act(() => {
      const editor = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(editor, 'Hello');
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Send"]')!.click());
    const status = container.querySelector('.chat-generation-status')!;
    expect(status.textContent).toContain('Awaiting model response');
    expect(status.nextElementSibling?.classList.contains('chat-composer')).toBe(true);
    expect(container.querySelectorAll('.chat-generation-status')).toHaveLength(1);
    expect(container.querySelector('.chat-message-assistant')?.textContent).toBe('');
    await act(async () => { finish(); await waiting; });
    expect(container.querySelector('.chat-generation-status')).toBeNull();
  });

  it('renders and saves a native chart request with Web off and no system instructions', async () => {
    localStorage.setItem('uncloud.chat.web', 'off');
    let pass = 0;
    vi.mocked(streamChat).mockImplementation(async function* () {
      if (pass++ === 0) yield { kind: 'tool_calls', text: '', tool_calls: [{ id: 'chart-1', type: 'function',
        function: { name: 'render_bar_chart', arguments: '{"title":"Sample data","labels":["A","B"],"values":[12,8]}' } }] };
      // A tool-only artifact is a complete answer, even without follow-up prose.
    });
    await mount();
    await send('Draw a bar chart of A 12 and B 8.');
    expect(container.querySelector('svg[role="img"]')?.getAttribute('aria-label')).toContain('Sample data');
    expect(webSearch).not.toHaveBeenCalled();
    expect(webRead).not.toHaveBeenCalled();
    expect(streamChat).toHaveBeenCalledTimes(1);
    const first = vi.mocked(streamChat).mock.calls[0];
    expect(first[0].some(turn => turn.role === 'system')).toBe(false);
    expect(first[3]?.chartTools).toBe(true);
    const saved = vi.mocked(writeConversation).mock.calls.at(-1)![1];
    expect(saved.messages.at(-1)?.content).toContain('```bar-chart');
    expect(saved.messages[0].tool_turns?.[0].tool_calls?.[0].id).toBe('chart-1');
    expect(saved.messages[0].tool_turns?.[1]).toMatchObject({ tool_call_id: 'chart-1', content: '{"rendered":true}' });
    expect(countChatContext).toHaveBeenCalledWith(expect.anything(), expect.anything(), false, false, true);
  });

  it.each([false, true])('returns data-only chart validation errors and accepts one correction with Web=%s', async web => {
    localStorage.setItem('uncloud.chat.web', web ? 'on' : 'off');
    let pass = 0;
    vi.mocked(streamChat).mockImplementation(async function* () {
      const extra = pass++ === 0 ? ',"colors":["red","blue"]' : '';
      yield { kind: 'tool_calls', text: '', tool_calls: [{ id: `chart-${pass}`, type: 'function',
        function: { name: 'render_bar_chart', arguments: `{"labels":["A","B"],"values":[12,8]${extra}}` } }] };
    });
    await mount();
    await send('Draw a bar chart of A 12 and B 8.');
    expect(streamChat).toHaveBeenCalledTimes(2);
    const corrected = vi.mocked(streamChat).mock.calls[1][0];
    expect(corrected.find(turn => turn.role === 'tool')).toMatchObject({
      content: '{"error":{"code":"additional_properties","fields":["colors"]}}',
    });
    expect(corrected.some(turn => turn.role === 'system')).toBe(false);
    expect(vi.mocked(streamChat).mock.calls[1][3]?.chartTools).toBe(true);
    expect(container.querySelectorAll('svg[role="img"] rect')).toHaveLength(2);
    expect(webSearch).not.toHaveBeenCalled();
  });

  it('stops after one failed chart correction instead of retrying indefinitely', async () => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      yield { kind: 'tool_calls', text: '', tool_calls: [{ id: 'bad-chart', type: 'function',
        function: { name: 'render_bar_chart', arguments: '{"labels":["A","B"],"values":[12]}' } }] };
    });
    await mount();
    await send('Draw a bar chart.');
    expect(streamChat).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('after one correction attempt');
    expect(container.querySelector('svg[role="img"]')).toBeNull();
  });

  it('applies only the explicitly chosen persona and saves it with its own conversation', async () => {
    const persona = { id: '0123456789abcdef', name: 'Storyteller', instructions: 'Write as a woodland storyteller.' };
    replies('Once upon a time.');
    await act(async () => root.render(<ChatView persona={persona} />));
    await send('Begin.');
    const turns = vi.mocked(streamChat).mock.calls[0][0];
    expect(turns.filter(t => t.role === 'system')).toEqual([{ role: 'system', content: persona.instructions }]);
    expect(writeConversation).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ persona }));
    expect(state.values).toEqual({});
    await act(() => root.unmount());
    root = createRoot(container);
    replies('An ordinary answer.');
    await mount();
    await send('Hello.');
    expect(vi.mocked(streamChat).mock.calls.at(-1)![0].some(t => t.role === 'system')).toBe(false);
  });

  it.each([
    ['Who discovered Neptune?', 'Neptune discovery NASA'],
    ['Could you find information about the James Webb telescope?', 'James Webb telescope NASA'],
    ['Look it up: how is sourdough made?', 'sourdough fermentation'],
    ['What are the latest iPhone specifications?', 'iPhone official specifications'],
  ])('accepts a model search request for %s', async (question, query) => {
    replies(`[[search: ${query}]]`, 'The answer cites https://example.org/source.');
    await mount();
    await send(question);
    expect(webSearch).toHaveBeenCalledExactlyOnceWith(query);
    expect(streamChat).toHaveBeenCalledTimes(2);
    const first = vi.mocked(streamChat).mock.calls[0][0];
    expect(first.some(turn => turn.role === 'system')).toBe(false);
    expect(vi.mocked(streamChat).mock.calls[0][3]?.webTools).toBe(true);
    const answer = vi.mocked(streamChat).mock.calls[1][0];
    expect(answer.some(turn => turn.content.includes('Verified test evidence.'))).toBe(true);
    expect(answer.some(turn => turn.content.includes(question))).toBe(true);
    expect(countChatContext).toHaveBeenCalled();
    expect(writeConversation).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
      messages: expect.arrayContaining([expect.objectContaining({ role: 'user', content: question,
        tool_turns: expect.arrayContaining([expect.objectContaining({ role: 'tool',
          content: expect.stringContaining('https://example.org/source') })]) })]),
    }));
  });

  it.each(['Hello, how are you?', 'Explain a binary search tree.', 'Search this array for 7.',
    'Write a specification for my app.', 'What are the latest constraints in this chat?'])(
    'does not fetch anything when the model answers %s directly', async (question) => {
      replies('A direct model answer.');
      await mount();
      await send(question);
      expect(streamChat).toHaveBeenCalledTimes(1);
      expect(webSearch).not.toHaveBeenCalled();
      expect(webRead).not.toHaveBeenCalled();
    },
  );

  it('lets the model resolve a lookup follow-up from the actual conversation', async () => {
    replies('We are discussing Neptune.', '[[search: Neptune discovery NASA]]', 'The sourced answer.');
    await mount();
    await send('Tell me about Neptune.');
    await send('Look it up.');
    expect(webSearch).toHaveBeenCalledExactlyOnceWith('Neptune discovery NASA');
    const turns = vi.mocked(streamChat).mock.calls[1][0];
    expect(turns.some(turn => turn.content === 'Tell me about Neptune.')).toBe(true);
    expect(turns.at(-1)?.content).toBe('Look it up.');
  });

  it('keeps web capability available alongside explicit custom instructions', async () => {
    state.values = { system_prompt: 'Use British spelling.' };
    replies('[[search: neutron star NASA]]', 'A sourced answer.');
    await mount();
    await send('Tell me about neutron stars.');
    const system = vi.mocked(streamChat).mock.calls[0][0].find(turn => turn.role === 'system')?.content;
    expect(system).toContain('Use British spelling.');
    expect(system).toBe('Use British spelling.');
    expect(webSearch).toHaveBeenCalledExactlyOnceWith('neutron star NASA');
  });

  it.each(['web-off', 'raw'])('blocks model lookups in %s mode', async (mode) => {
    localStorage.setItem(mode === 'raw' ? 'uncloud.debug.raw' : 'uncloud.chat.web', mode === 'raw' ? 'on' : 'off');
    replies('[[search: Neptune NASA]]');
    await mount();
    await send('Look up Neptune.');
    expect(webSearch).not.toHaveBeenCalled();
    expect(webRead).not.toHaveBeenCalled();
    expect(streamChat).toHaveBeenCalledTimes(1);
    expect(vi.mocked(streamChat).mock.calls[0][0].some(turn => turn.role === 'system')).toBe(false);
  });

  it('never executes lookup markers inside private reasoning', async () => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      yield { kind: 'thinking', text: '[[search: Neptune NASA]]' };
      yield { kind: 'text', text: 'An ordinary answer.' };
    });
    await mount();
    await send('Tell me about Neptune.');
    expect(webSearch).not.toHaveBeenCalled();
    expect(webRead).not.toHaveBeenCalled();
  });

  it('accepts a model-requested source read without a user URL or matching keyword', async () => {
    replies('[[read: https://example.org/source]]', 'The sourced answer.');
    await mount();
    await send('Tell me about Neptune.');
    expect(webRead).toHaveBeenCalledExactlyOnceWith('https://example.org/source');
    expect(webSearch).not.toHaveBeenCalled();
    expect(streamChat).toHaveBeenCalledTimes(2);
  });

  it('stops repeated lookup requests without repeating the search', async () => {
    replies('[[search: Neptune NASA]]', '[[search: Neptune NASA]]', 'The answer from the source.');
    await mount();
    await send('Tell me about Neptune.');
    expect(webSearch).toHaveBeenCalledExactlyOnceWith('Neptune NASA');
    expect(streamChat).toHaveBeenCalledTimes(3);
    expect(vi.mocked(streamChat).mock.calls[2][3]?.webTools).toBe(false);
    expect(vi.mocked(streamChat).mock.calls[2][0].some(t => t.role === 'tool')).toBe(true);
  });

  it('reads an explicitly requested URL once before generating the answer', async () => {
    replies('An answer based on the supplied page.');
    await mount();
    await send('Read https://example.org/source and summarize it.');
    expect(webRead).toHaveBeenCalledExactlyOnceWith('https://example.org/source');
    expect(webSearch).not.toHaveBeenCalled();
    expect(streamChat).toHaveBeenCalledTimes(1);
  });

  it('returns a structured provider failure so the model can refine its query', async () => {
    vi.mocked(webSearch).mockRejectedValueOnce(new Error('The provider did not return results.'));
    replies('[[search: Neptune NASA]]', '[[search: Neptune discovery observatory]]', 'A sourced answer.');
    await mount();
    await send('Tell me about Neptune.');
    expect(webSearch).toHaveBeenCalledTimes(2);
    expect(webSearch).toHaveBeenLastCalledWith('Neptune discovery observatory');
    expect(streamChat).toHaveBeenCalledTimes(3);
    const failure = vi.mocked(streamChat).mock.calls[1][0].find(t => t.role === 'tool');
    expect(JSON.parse(failure!.content)).toEqual({error: {
      code: 'lookup_failed', message: 'The provider did not return results.',
    }});
  });

  it('does not execute search requests in ordinary answer text', async () => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      yield { kind: 'text', text: 'Example: [[search: Neptune NASA]].' };
    });
    await mount();
    await send('Explain how search works.');
    expect(webSearch).not.toHaveBeenCalled();
    expect(webRead).not.toHaveBeenCalled();
  });

  it('rejects an unknown native tool without executing it', async () => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      yield { kind: 'tool_calls', text: '', tool_calls: [{ id: 'x', type: 'function',
        function: { name: 'fs_write', arguments: '{"path":"bad"}' } }] };
    });
    await mount();
    await send('Find a source.');
    expect(webSearch).not.toHaveBeenCalled();
    expect(webRead).not.toHaveBeenCalled();
    expect(container.textContent).toContain('Unsupported native tool');
  });

  it('includes the enabled web contract in the context meter before a lookup', async () => {
    vi.useFakeTimers();
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(550); });
    const counted = vi.mocked(countChatContext).mock.calls.at(-1)![0];
    expect(counted.some(turn => turn.role === 'system')).toBe(false);
    expect(vi.mocked(countChatContext).mock.calls.at(-1)![2]).toBe(true);
    expect(webSearch).not.toHaveBeenCalled();
    expect(streamChat).not.toHaveBeenCalled();
  });
});
