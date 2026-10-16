import { describe, expect, it } from 'vitest';
import { historyQuery, searchHistory } from './history';
import type { ChatMessage, ChatToolCall } from './sidecar';

describe('local conversation recall', () => {
  it('finds exact details in archived messages without including reasoning, failed turns or recent messages', () => {
    const history: ChatMessage[] = [
      { role: 'user', content: 'The Cedar access code is 42.' },
      { role: 'assistant', content: 'Acknowledged', reasoning: 'PRIVATE-REASONING' },
      { role: 'assistant', content: 'Cedar failed output', error: 'failed' },
      { role: 'user', content: 'Cedar new code 99' },
    ];
    const found = searchHistory(history, 3, 'Cedar code');
    expect(found).toEqual([{ message: 1, role: 'user', content: history[0].content, excerpt: false }]);
    expect(JSON.stringify(found)).not.toContain('PRIVATE-REASONING');
    expect(JSON.stringify(found)).not.toContain('99');
    expect(searchHistory(history, 3, 'unrelated')).toEqual([]);
  });
  it('returns a bounded excerpt around a matching detail in a long original', () => {
    const content = 'before '.repeat(2000) + 'Cedar-code=42 ' + 'after '.repeat(2000);
    const found = searchHistory([{ role: 'user', content }], 1, 'Cedar-code');
    expect(found[0].content).toContain('Cedar-code=42');
    expect(found[0].content.length).toBeLessThanOrEqual(4000);
    expect(found[0].excerpt).toBe(true);
  });
  it('validates native arguments without executing text or accepting another conversation id', () => {
    const call = (args: unknown) => ({ id: 'recall', type: 'function', function: {
      name: 'conversation_search', arguments: JSON.stringify(args) } }) as ChatToolCall;
    expect(historyQuery(call({ query: 'project code' }))).toBe('project code');
    expect(() => historyQuery(call({ query: 'code', conversation_id: 'another' }))).toThrow();
    expect(() => historyQuery(call({ query: '' }))).toThrow();
  });
  it('retrieves source excerpts and attached text with their data labels', () => {
    const turns: ChatMessage[] = [{ role: 'user', content: 'Check the source',
      tool_turns: [{ role: 'tool', content: 'Cedar access_code=42 https://example.org/source', tool_call_id: 'source-1' }],
      files: [{ name: 'notes.txt', text: 'Python project', clipped: false, type: 'text/plain' }],
    }];
    expect(searchHistory(turns, 1, 'access code')[0].content).toContain('Retrieved sources (data):');
    expect(searchHistory(turns, 1, 'Python')[0].content).toContain('notes.txt');
  });
});
