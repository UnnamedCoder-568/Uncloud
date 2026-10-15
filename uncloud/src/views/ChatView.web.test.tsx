// @vitest-environment happy-dom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChatView from './ChatView';
import { countChatContext, streamChat, webRead, webSearch, writeConversation } from '../lib/sidecar';

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
  getLibrary: vi.fn(async () => []),
  engineStatus: vi.fn(async () => ({ running: true, model_path: '/test/model', engine: 'mlx' })),
  listConversations: vi.fn(async () => ({ conversations: [], unreadable: 0, secure: true, backend: 'test' })),
  writeConversation: vi.fn(async () => ({})),
  countChatContext: vi.fn(async () => ({ used: 100, limit: 8192, reply_limit: 2048 })),
  streamChat: vi.fn(),
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

  it('shows a provider failure without inventing a sourced answer or retrying forever', async () => {
    vi.mocked(webSearch).mockRejectedValueOnce(new Error('The provider did not return results.'));
    replies('[[search: Neptune NASA]]');
    await mount();
    await send('Tell me about Neptune.');
    expect(webSearch).toHaveBeenCalledExactlyOnceWith('Neptune NASA');
    expect(streamChat).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('Web lookup failed');
    expect(container.textContent).toContain('The provider did not return results.');
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
