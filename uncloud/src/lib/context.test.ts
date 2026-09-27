import { describe, expect, it } from 'vitest';
import { contextMessages, compactAvailable } from './context';
import type { ChatMessage } from './sidecar';

describe('conversation context', () => {
  const turns: ChatMessage[] = [
    { role: 'user', content: 'Use Python' }, { role: 'assistant', content: 'Agreed' },
    { role: 'user', content: 'Continue' },
  ];
  it('keeps one system message and the uncompressed tail', () => {
    const sent = contextMessages(turns, 'Assistant', 'Constraint: Python', 2);
    expect(sent).toHaveLength(2);
    expect(sent[0].content).toContain('Constraint: Python');
    expect(sent[1]).toEqual(turns[2]);
    expect(turns).toHaveLength(3); // Original transcript remains inspectable.
  });
  it('never drops turns without an actual summary', () => {
    expect(contextMessages(turns, 'Assistant', '', 2)).toHaveLength(4);
  });
  it('raw baseline bypasses the system prompt and memory', () => {
    expect(contextMessages(turns, 'Assistant', 'Memory', 2, true)).toBe(turns);
  });
  it('offers compact at 75 percent of the actual limit', () => {
    expect(compactAvailable(6143, 8192)).toBe(false);
    expect(compactAvailable(6144, 8192)).toBe(true);
    expect(compactAvailable(6144, 131072)).toBe(false);
    expect(compactAvailable(null, 8192)).toBe(false);
  });
});
