import type { ChatMessage } from './sidecar';

/** One assembly path for both inference and the context meter. */
export function contextMessages(messages: ChatMessage[], system: string,
  summary = '', through = 0, raw = false): ChatMessage[] {
  // Failed requests remain inspectable in the transcript, but their user turn
  // and application error must not become a malformed model conversation.
  const failed = new Set<number>();
  messages.forEach((message, index) => {
    if (message.role === 'assistant' && message.error && !message.content.trim()) {
      failed.add(index);
      if (messages[index - 1]?.role === 'user') failed.add(index - 1);
    }
  });
  const turns = failed.size ? messages.filter((_, index) => !failed.has(index)) : messages;
  if (raw) return turns;
  let memory: unknown = summary;
  if (summary) { try { memory = JSON.parse(summary); } catch { /* Legacy text memory stays data. */ } }
  const content = [system, summary ? JSON.stringify({ conversation_memory: memory }) : ''].filter(Boolean).join('\n\n');
  const start = through;
  const tail = messages.slice(start).filter((_, index) => !failed.has(index + start));
  return [...(content ? [{ role: 'system' as const, content }] : []), ...tail.flatMap(message => {
    const { tool_turns: tools, ...turn } = message;
    return [message.retrieved
      ? { ...turn, content: `${message.content}\n\n${message.retrieved}`, retrieved: undefined }
      : turn, ...(tools ?? [])];
  })];
}

export function compactAvailable(used: number | null, limit: number | null): boolean {
  return used != null && limit != null && limit > 0 && used / limit >= 0.75;
}
