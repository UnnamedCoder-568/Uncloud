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
  const content = system + (summary ? `\n\nEarlier conversation, compacted for continuity:\n${summary}` : '');
  const start = summary ? through : 0;
  const tail = messages.slice(start).filter((_, index) => !failed.has(index + start));
  return [{ role: 'system', content }, ...tail.map(message => message.retrieved
    ? { ...message, content: `${message.content}\n\n${message.retrieved}`, retrieved: undefined }
    : message)];
}

export function compactAvailable(used: number | null, limit: number | null): boolean {
  return used != null && limit != null && limit > 0 && used / limit >= 0.75;
}

/** Shared with the live-model compaction evaluation. */
export const COMPACTION_INSTRUCTION = `Summarize this conversation for continued work in the same chat.
Use these headings: Current facts and decisions; Active constraints; Open tasks; References.
Preserve the user's intent, project state, exact names and paths, necessary references and unresolved tasks.
For each changed decision, record only the latest authoritative value as current. Do not mix old and new values with arrows. Omit superseded values unless still needed, and explicitly label them superseded.
Remove completed tasks from Open tasks. Preserve unchanged decisions and prohibitions from existing memory.
Distinguish verified facts from guesses. Keep task wording and names exact. Be concise and do not invent details.`;
