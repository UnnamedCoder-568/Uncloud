import { describe, expect, it, vi } from 'vitest';
import { prepareConversation } from './dynamic-context';
import type { ChatMessage } from './sidecar';

const history: ChatMessage[] = [
  { role: 'user', content: 'Project Cedar, code 42. '.repeat(20) },
  { role: 'assistant', content: 'Earlier details. '.repeat(25) },
  { role: 'user', content: 'Recent question. '.repeat(12) },
  { role: 'assistant', content: 'Recent answer. '.repeat(12) },
  { role: 'user', content: 'What was the code?' },
];
const count = async (turns: ChatMessage[], archived = false) => ({
  used: turns.reduce((sum, turn) => sum + turn.content.length, 20) + (archived ? 100 : 0),
  limit: 1000, exact: true,
});
describe('dynamic conversation context', () => {
  it('does no summary work while the native prompt fits comfortably', async () => {
    const compact = vi.fn();
    const result = await prepareConversation([history.at(-1)!], {
      summary: '', through: 0, system: '', count, compact,
    });
    expect(compact).not.toHaveBeenCalled();
    expect(result.through).toBe(0);
  });
  it('compacts older exchanges, keeps recent messages, and preserves the originals', async () => {
    const original = JSON.stringify(history);
    const compact = vi.fn(async () => 'Project Cedar, code 42.');
    const result = await prepareConversation(history, { summary: '', through: 0, system: '', count, compact });
    expect(compact).toHaveBeenCalledTimes(1);
    expect(result.through).toBe(2);
    expect(result.tail).toEqual(history.slice(2));
    expect(result.usage.used).toBeLessThan(750);
    expect(JSON.stringify(history)).toBe(original);
  });
  it.each(['failure', 'oversized'])('uses a measured recent window after a %s summary without retrying', async (failure) => {
    const compact = vi.fn(async () => {
      if (failure === 'failure') throw new Error('summary timed out');
      return 'Unhelpful memory '.repeat(500);
    });
    const result = await prepareConversation(history, { summary: '', through: 0, system: '', count, compact });
    expect(compact).toHaveBeenCalledTimes(1);
    expect(result.summary).toBe('');
    expect(result.through).toBeGreaterThan(0);
    expect(result.usage.used).toBeLessThanOrEqual(750);
    expect(result.notice).toContain('saved for recall');
    expect(history).toHaveLength(5);
  });
  it('does not swallow cancellation or continue summarizing', async () => {
    const controller = new AbortController();
    const compact = vi.fn(async () => { controller.abort(); return 'Memory'; });
    await expect(prepareConversation(history, { summary: '', through: 0, system: '', count, compact,
      signal: controller.signal })).rejects.toThrow();
    expect(compact).toHaveBeenCalledTimes(1);
  });
  it('preserves a single oversized latest message for evidence fitting or reports it clearly', async () => {
    const compact = vi.fn();
    const turns: ChatMessage[] = [{ role: 'user', content: 'x'.repeat(2000) }];
    await expect(prepareConversation(turns, { summary: '', through: 0, system: '', count, compact })).rejects.toThrow('latest message');
    const result = await prepareConversation(turns, { summary: '', through: 0, system: '', count, compact, allowOverflow: true });
    expect(result.tail).toEqual(turns);
    expect(compact).not.toHaveBeenCalled();
  });
});
