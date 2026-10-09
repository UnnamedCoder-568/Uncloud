import type { ChatContextUsage, ChatMessage } from './sidecar';

/** Reduce retrieved material, never the user's conversation. Keep source URLs
 * even when page excerpts need shortening. Token counts use the live template. */
export async function fitWebContext(
  evidence: string,
  assemble: (evidence: string) => ChatMessage[],
  count: (messages: ChatMessage[]) => Promise<ChatContextUsage>,
  replyBudget?: number,
): Promise<{ evidence: string; usage: ChatContextUsage; replyBudget: number }> {
  const original = await count(assemble(evidence));
  if (original.used == null || !original.limit) {
    throw new Error('Could not check the model’s available context for web results. Your conversation is preserved.');
  }
  const reserve = replyBudget ?? Math.max(1, Math.floor(original.limit / 4));
  const fits = (usage: ChatContextUsage) => usage.used != null && usage.used + reserve <= original.limit!;
  if (fits(original)) return { evidence, usage: original, replyBudget: reserve };
  const blocks = evidence.split(/\n\n+/);
  const excerpt = (fraction: number) => blocks.map(block => {
    const lines = block.split('\n');
    return lines.map((line, index) => index === 0 || /https?:\/\//.test(line)
      ? line : line.slice(0, Math.floor(line.length * fraction))).filter(Boolean).join('\n');
  }).join('\n\n') + '\n[Source excerpts shortened to fit this model’s context. Evidence may be incomplete.]';
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
  return { evidence: selected, usage, replyBudget: reserve };
}
