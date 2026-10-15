import type { ChatToolCall } from './sidecar';
import type { Lookup } from './lookup';

/** Assemble only structured backend tool deltas, never answer or thinking text. */
export class ToolCallAccumulator {
  private calls = new Map<number, ChatToolCall>();

  push(deltas: { index?: number; id?: string; type?: string;
    function?: { name?: string; arguments?: string | Record<string, unknown> } }[]) {
    for (const delta of deltas) {
      const index = delta.index ?? 0;
      if (!Number.isInteger(index) || index < 0 || index >= 16) throw new Error('Invalid native tool call index.');
      const call = this.calls.get(index) ?? { id: '', type: 'function', function: { name: '', arguments: '' } };
      if (delta.id && delta.id !== call.id) call.id += delta.id;
      const name = delta.function?.name;
      if (name && name !== call.function.name) call.function.name += name;
      const args = delta.function?.arguments;
      if (args) call.function.arguments += typeof args === 'string' ? args : JSON.stringify(args);
      if (call.function.arguments.length > 32000 || call.id.length > 256) throw new Error('Native tool call is too large.');
      this.calls.set(index, call);
    }
  }

  finish(): ChatToolCall[] {
    const calls = [...this.calls.entries()].sort(([a], [b]) => a - b).map(([, call]) => call);
    if (calls.some(c => !c.id || !c.function.name) || new Set(calls.map(c => c.id)).size !== calls.length) {
      throw new Error('The model returned an incomplete native tool call.');
    }
    return calls;
  }
}

export function lookupForTool(call: ChatToolCall): Lookup {
  const name = call.function.name;
  if (!['web_search', 'web_read'].includes(name)) {
    throw new Error(`Unsupported native tool: ${name}`);
  }
  let args: Record<string, unknown>;
  try { args = JSON.parse(call.function.arguments); }
  catch { throw new Error('The model returned invalid web tool arguments.'); }
  const field = name === 'web_search' ? 'query' : 'url';
  const argument = args?.[field];
  if (!args || typeof args !== 'object' || typeof argument !== 'string' || !argument.trim()
      || argument.length > 16000 || Object.keys(args).some(k => k !== field)) {
    throw new Error('The model returned invalid web tool arguments.');
  }
  return { kind: name === 'web_search' ? 'search' : 'read', argument: argument.trim() };
}
