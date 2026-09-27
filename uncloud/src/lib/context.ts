import type { ChatMessage } from './sidecar';

/** One assembly path for both inference and the context meter. */
export function contextMessages(messages: ChatMessage[], system: string,
  summary = '', through = 0, raw = false): ChatMessage[] {
  if (raw) return messages;
  const content = system + (summary ? `\n\nEarlier conversation, compacted for continuity:\n${summary}` : '');
  return [{ role: 'system', content }, ...messages.slice(summary ? through : 0)];
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
