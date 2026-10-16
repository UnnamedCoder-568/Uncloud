import { contextMessages } from './context';
import type { ChatContextUsage, ChatMessage } from './sidecar';

export interface Continuity { summary: string; through: number }
interface Options extends Continuity {
  system: string;
  count: (turns: ChatMessage[], archived: boolean) => Promise<ChatContextUsage>;
  compact: (turns: ChatMessage[], memory: string) => Promise<string>;
  signal?: AbortSignal;
  allowOverflow?: boolean;
}

/** Prepare a rolling native context while keeping the complete transcript.
 * At most two summary operations; failures fall back to a measured recent
 * window with local history retrieval, never a retry/summarization loop. */
export async function prepareConversation(history: ChatMessage[], options: Options) {
  let { summary, through } = options;
  let notice = '';
  const check = () => options.signal?.throwIfAborted();
  const measure = async (memory: string, boundary: number) => {
    check();
    const usage = await options.count(contextMessages(history, options.system, memory, boundary), boundary > 0);
    check();
    return usage;
  };
  let usage = await measure(summary, through);
  const comfortable = () => usage.used == null || !usage.limit || usage.used <= usage.limit * 0.75;
  const users = history.flatMap((message, index) => message.role === 'user' ? [index] : []);
  const latest = users.at(-1) ?? 0;
  const candidates = [...new Set([users.at(-2) ?? latest, latest])].filter(index => index > through);
  if (!comfortable()) for (const boundary of candidates) {
    try {
      const memory = (await options.compact(history.slice(through, boundary), summary)).trim();
      check();
      if (!memory) throw new Error('The model returned an empty summary.');
      const after = await measure(memory, boundary);
      if (after.used == null || usage.used == null || after.used >= usage.used) {
        throw new Error('The summary did not reduce context.');
      }
      summary = memory; through = boundary; usage = after;
      notice = 'Earlier messages compacted. Originals remain available for recall.';
    } catch (error) {
      check();
      notice = `Summary unavailable (${error instanceof Error ? error.message : String(error)}). Older messages remain saved for recall.`;
      break;
    }
    if (comfortable()) break;
  }
  if (!comfortable() && latest > through) {
    // Drop only complete older exchanges from the active window. The caller
    // retains and saves every original message, and exposes scoped retrieval.
    const boundaries = users.filter(index => index > through && index <= latest);
    let low = 0, high = boundaries.length - 1;
    let selected = latest;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      const measured = await measure(summary, boundaries[middle]);
      if (measured.used != null && measured.limit && measured.used <= measured.limit * 0.75) {
        selected = boundaries[middle]; high = middle - 1;
      } else low = middle + 1;
    }
    through = selected;
    usage = await measure(summary, through);
    notice ||= 'Recent messages are in context. Older messages remain saved for recall.';
  }
  if (!options.allowOverflow && usage.used != null && usage.limit && usage.used >= usage.limit) {
    throw new Error('The latest message and retained memory exceed the loaded context. Original history is preserved.');
  }
  return { summary, through, usage, notice, tail: history.slice(through) };
}
