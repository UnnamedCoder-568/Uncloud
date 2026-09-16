/** Passing a conversation from Chat to Chisel.
 *
 *  Deliberately a tiny module rather than a context or a store. The two views
 *  are siblings that stay mounted, and what passes between them is one
 *  message, once — a context provider spanning the whole application for that
 *  would be more machinery than the problem has.
 *
 *  The handoff carries a COPY. Chat keeps its conversation, because handing
 *  work over and then finding the discussion gone would be the wrong trade:
 *  the discussion is often what the work is checked against.
 */

import type { ChatMessage } from './sidecar';

export interface Handoff {
  /** What Chisel should actually do. The last thing the user asked for. */
  goal: string;
  /** The conversation it came out of, as background for planning. */
  context: { role: string; content: string }[];
  /** The exact planning model Chat was using. Chisel reloads it if image or
   * audio work evicted it between the handoff and the socket opening. */
  model?: { path: string; engine: string; name: string };
}

type Listener = () => void;

const listeners = new Set<Listener>();

//: The handoff waiting to be picked up. Held rather than pushed, because two
//  different parts of the application react to one: the shell switches to
//  Chisel, and Chisel does the work. Pushing the value to both would mean
//  whichever ran first consumed it. Holding it lets the shell react to the
//  SIGNAL while only Chisel takes the VALUE — and it survives Chisel not being
//  mounted yet, which is the usual case the first time.
let pending: Handoff | null = null;

/** Be told a handoff has been made. The value is not delivered here; call
 *  `takeHandoff` for that. */
export function onHandoffSignal(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Claim the waiting handoff, if there is one. Returns it once. */
export function takeHandoff(): Handoff | null {
  const held = pending;
  pending = null;
  return held;
}

export function sendToChisel(handoff: Handoff): void {
  pending = handoff;
  for (const listener of listeners) listener();
}

/** What to hand over, from a conversation.
 *
 *  The goal is the user's last message: it is what they asked for, and every
 *  earlier turn is background rather than instruction. Falling back to the
 *  whole exchange when there is no user turn is safe — an empty goal is
 *  refused by the engine, and an odd one is visible in the field before it
 *  runs.
 */
export function fromConversation(
  messages: ChatMessage[], model?: { path: string; engine: string; name: string } | null,
): Handoff {
  const conversation = messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => ({
      role: m.role,
      content: m.content + (m.files ?? []).map((file) =>
        `\n\n--- Attached file: ${file.name}${file.clipped ? ' (excerpt)' : ''} ---\n${file.text}`,
      ).join(''),
    }));
  const lastUser = [...conversation].reverse().find((m) => m.role === 'user');
  return {
    goal: lastUser?.content.trim() ?? '',
    // Everything BEFORE the goal. Repeating the goal inside its own background
    // makes a small model plan it twice.
    context: lastUser
      ? conversation.slice(0, conversation.lastIndexOf(lastUser))
      : conversation,
    ...(model ? { model: { path: model.path, engine: model.engine, name: model.name } } : {}),
  };
}
