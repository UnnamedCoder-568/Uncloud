import type { ChatContextUsage, ChatMessage } from './sidecar';

/** Shorten source values while retaining valid structured results and URLs. */
function sourceExcerpt(text: string, fraction: number): string {
  const shorten = (value: string) => value.split(/\n\n+/).map(block =>
    block.split('\n').map((line, index) => {
      const urls = line.match(/https?:\/\/[^\s<>"']+/g) ?? [];
      const length = Math.max(index === 0 ? Math.min(160, line.length) : 0,
        Math.floor(line.length * fraction));
      const prefix = line.slice(0, length);
      return [prefix, ...urls.filter(url => !prefix.includes(url))].filter(Boolean).join(' ');
    }).filter(Boolean).join('\n')).join('\n\n');
  try {
    const data = JSON.parse(text);
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      const walk = (value: unknown): unknown => typeof value === 'string' ? shorten(value)
        : Array.isArray(value) ? value.map(walk)
        : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(
          ([key, item]) => [key, walk(item)])) : value;
      return JSON.stringify({ ...walk(data) as object, source_excerpt: 'partial' });
    }
  } catch { /* A plain retrieved page remains plain text. */ }
  return shorten(text) + '\n{"source_excerpt":"partial"}';
}

/** Reduce retrieved material, never the user's conversation. Keep source URLs
 * even when page excerpts need shortening. Token counts use the live template. */
export async function fitWebContext(
  evidence: string,
  assemble: (evidence: string) => ChatMessage[],
  count: (messages: ChatMessage[]) => Promise<ChatContextUsage>,
  replyBudget?: number,
): Promise<{ evidence: string; usage: ChatContextUsage; replyBudget: number }> {
  const result = await fitToolContext([evidence], values => assemble(values[0]), count, replyBudget);
  return { ...result, evidence: result.evidence[0] };
}

/** Fit a whole native tool batch together, retaining each call ID and every
 * source URL. A greedy per-result fit can starve later results in the batch. */
export async function fitToolContext(
  evidence: string[],
  assemble: (evidence: string[]) => ChatMessage[],
  count: (messages: ChatMessage[]) => Promise<ChatContextUsage>,
  replyBudget?: number,
): Promise<{ evidence: string[]; usage: ChatContextUsage; replyBudget: number }> {
  const original = await count(assemble(evidence));
  if (original.used == null || !original.limit) {
    throw new Error('Could not check the model’s available context for web results. Your conversation is preserved.');
  }
  // Saved ceilings can exceed a newly selected runtime window. They are
  // maxima, not reservations that should make every request impossible.
  const automatic = Math.min(original.reply_limit ?? Math.max(1, Math.floor(original.limit / 4)),
    Math.max(1, Math.floor(original.limit / 4)));
  const reserve = replyBudget != null && replyBudget < original.limit ? replyBudget : automatic;
  const fits = (usage: ChatContextUsage) => usage.used != null && usage.used + reserve <= original.limit!;
  // The fitting reserve is not the generation ceiling. Auto can use all space
  // remaining after the final prompt; a saved manual ceiling is never raised.
  const outputLimit = (usage: ChatContextUsage) => Math.min(
    replyBudget ?? original.reply_limit ?? original.limit!, original.limit! - usage.used!);
  if (fits(original)) return { evidence, usage: original, replyBudget: outputLimit(original) };
  const excerpt = (fraction: number) => evidence.map(text => sourceExcerpt(text, fraction));
  let selected = excerpt(0);
  let usage = await count(assemble(selected));
  if (!fits(usage)) {
    throw new Error('This model’s current context window cannot fit the conversation, web sources and reply. Compact the conversation or load a model with more available context. Your conversation is preserved.');
  }
  let low = 0, high = 1;
  for (let attempt = 0; attempt < 7; attempt++) {
    const fraction = (low + high) / 2;
    const candidate = excerpt(fraction);
    const measured = await count(assemble(candidate));
    if (fits(measured)) { low = fraction; selected = candidate; usage = measured; }
    else high = fraction;
  }
  return { evidence: selected, usage, replyBudget: outputLimit(usage) };
}
