import { describe, expect, it } from 'vitest';
import { ToolCallAccumulator, lookupForTool } from './native-tools';

describe('native web tool streaming', () => {
  it('joins interleaved argument fragments and keeps call IDs', () => {
    const stream = new ToolCallAccumulator();
    stream.push([{ index: 0, id: 'call_a', type: 'function', function: { name: 'web_search', arguments: '{"query":"Nep' } }]);
    stream.push([{ index: 1, id: 'call_b', type: 'function', function: { name: 'web_read', arguments: '{"url":"https://example.org"}' } }]);
    stream.push([{ index: 0, function: { arguments: 'tune"}' } }]);
    const calls = stream.finish();
    expect(calls.map(c => c.id)).toEqual(['call_a', 'call_b']);
    expect(lookupForTool(calls[0])).toEqual({ kind: 'search', argument: 'Neptune' });
    expect(lookupForTool(calls[1])).toEqual({ kind: 'read', argument: 'https://example.org' });
  });
  it('does not execute text that merely resembles a tool request', () => {
    expect(new ToolCallAccumulator().finish()).toEqual([]);
  });
  it('rejects unknown tools and malformed arguments before any network work', () => {
    const make = (name: string, args: string) => ({ id: 'a', type: 'function' as const,
      function: { name, arguments: args } });
    expect(() => lookupForTool(make('fs_read', '{"path":"/private"}'))).toThrow('Unsupported');
    expect(() => lookupForTool(make('get_model_info', '{}'))).toThrow('Unsupported');
    expect(() => lookupForTool(make('web_search', 'not json'))).toThrow('arguments');
    expect(() => lookupForTool(make('web_search', '{"query":false}'))).toThrow('arguments');
    expect(() => lookupForTool(make('web_search', '{"query":""}'))).toThrow('arguments');
  });
});
