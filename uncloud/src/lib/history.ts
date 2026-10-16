import type { ChatMessage, ChatToolCall } from './sidecar';

const terms = (text: string) => text.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];

/** Local lexical retrieval over original visible messages. No embedding model,
 * network request, private reasoning, or access to another conversation. */
export function searchHistory(messages: ChatMessage[], through: number, query: string) {
  const words = new Set(terms(query));
  const docs = messages.slice(0, through).flatMap((message, index) => {
    if (!['user', 'assistant'].includes(message.role) || message.error) return [];
    const sources = [message.retrieved, ...(message.tool_turns ?? [])
      .filter(turn => turn.role === 'tool').map(turn => turn.content)].filter(Boolean).join('\n\n');
    const content = [message.content, ...(message.files ?? []).map(file => `${file.name}\n${file.text}`),
      sources ? `Retrieved sources (data):\n${sources}` : '']
      .filter(Boolean).join('\n');
    return content ? [{ message: index + 1, role: message.role, content, words: terms(content) }] : [];
  });
  const frequencies = new Map<string, number>();
  for (const doc of docs) for (const word of new Set(doc.words)) {
    if (words.has(word)) frequencies.set(word, (frequencies.get(word) ?? 0) + 1);
  }
  const average = docs.reduce((total, doc) => total + doc.words.length, 0) / (docs.length || 1);
  return docs.map(doc => {
    let score = 0;
    const occurrences = new Map<string, number>();
    for (const word of doc.words) if (words.has(word)) occurrences.set(word, (occurrences.get(word) ?? 0) + 1);
    for (const [word, frequency] of occurrences) {
      const idf = Math.log(1 + (docs.length - frequencies.get(word)! + 0.5) / (frequencies.get(word)! + 0.5));
      score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * doc.words.length / (average || 1)));
    }
    return { ...doc, score };
  }).filter(doc => doc.score > 0).sort((a, b) => b.score - a.score).slice(0, 6)
    .sort((a, b) => a.message - b.message).map(doc => {
      const folded = doc.content.toLocaleLowerCase();
      const hit = Math.min(...[...words].map(word => folded.indexOf(word)).filter(index => index >= 0));
      const start = doc.content.length > 4000 ? Math.max(0, hit - 1000) : 0;
      return { message: doc.message, role: doc.role, content: doc.content.slice(start, start + 4000),
        excerpt: start > 0 || doc.content.length > 4000 };
    });
}

export function historyQuery(call: ChatToolCall): string {
  let args: Record<string, unknown>;
  try { args = JSON.parse(call.function.arguments); }
  catch { throw new Error('Invalid conversation search arguments.'); }
  if (!args || typeof args !== 'object' || typeof args.query !== 'string' || !args.query.trim()
    || args.query.length > 16000 || Object.keys(args).some(key => key !== 'query')) {
    throw new Error('Invalid conversation search arguments.');
  }
  return args.query;
}
