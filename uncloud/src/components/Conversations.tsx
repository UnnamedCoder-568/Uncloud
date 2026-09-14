/** The list of saved conversations.
 *
 *  A drawer rather than a permanent column: the conversation is the work, and
 *  a list of other conversations is navigation. It earns space when asked for
 *  and gives it back afterwards.
 */

import { useEffect, useState } from 'react';
import { MessageSquare, Plus, Trash2, X } from 'lucide-react';

import type { ConversationList, ConversationSummary } from '../lib/sidecar';

function when(seconds: number): string {
  if (!seconds) return '';
  const date = new Date(seconds * 1000);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }
  const year = date.getFullYear() === now.getFullYear() ? undefined : 'numeric';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year });
}

export interface ConversationsProps {
  open: boolean;
  onClose: () => void;
  list: ConversationList | null;
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export default function Conversations({ open, onClose, list, activeId,
                                        onOpen, onNew, onDelete }: ConversationsProps) {
  //: Which row is asking to be confirmed. A conversation is work, and one
  //  click from a stray cursor should not end it — but a modal for every
  //  delete is heavier than the action deserves, so the row asks in place.
  const [confirming, setConfirming] = useState<string | null>(null);

  useEffect(() => {
    if (!open) setConfirming(null);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const items: ConversationSummary[] = list?.conversations ?? [];

  return (
    <div className="absolute inset-0 z-30 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <aside className="w-[300px] h-full bg-[var(--bg-raised)] border-l border-[var(--border)]
                        flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--border-soft)]">
          <span className="text-xs uppercase tracking-wide text-[var(--text-faint)]">
            Conversations
          </span>
          <button className="tb-btn" onClick={onClose} title="Close">
            <X size={14} />
          </button>
        </div>

        <button
          className="flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-[var(--bg-inset)]
                     border-b border-[var(--border-soft)] text-left"
          onClick={() => { onNew(); onClose(); }}
        >
          <Plus size={14} /> New conversation
        </button>

        <div className="flex-1 overflow-y-auto chassis-scroll py-1">
          {items.length === 0 && (
            <p className="px-3 py-4 text-xs text-[var(--text-faint)] leading-relaxed">
              Nothing saved yet. A conversation is kept as soon as you send the
              first message, and stays here between sessions.
            </p>
          )}

          {items.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center gap-2 px-3 py-2 cursor-pointer
                          ${c.id === activeId ? 'bg-[var(--bg-inset)]' : 'hover:bg-[var(--bg-inset)]'}`}
              onClick={() => { if (!confirming) { onOpen(c.id); onClose(); } }}
            >
              <MessageSquare size={13} className="shrink-0 text-[var(--text-faint)]" />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] truncate">{c.title || 'Untitled'}</div>
                <div className="text-[10px] text-[var(--text-faint)]">
                  {when(c.updated)} · {c.messages} {c.messages === 1 ? 'message' : 'messages'}
                </div>
              </div>

              {confirming === c.id ? (
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    className="text-[11px] text-rose-400 px-1.5 py-0.5 rounded hover:bg-rose-500/10"
                    onClick={(e) => { e.stopPropagation(); onDelete(c.id); setConfirming(null); }}
                  >
                    Delete
                  </button>
                  <button
                    className="text-[11px] text-[var(--text-faint)] px-1.5 py-0.5 rounded
                               hover:bg-[var(--bg-raised)]"
                    onClick={(e) => { e.stopPropagation(); setConfirming(null); }}
                  >
                    Keep
                  </button>
                </div>
              ) : (
                <button
                  className="tb-btn shrink-0 opacity-0 group-hover:opacity-100 touch:opacity-100 focus:opacity-100"
                  title="Delete"
                  onClick={(e) => { e.stopPropagation(); setConfirming(c.id); }}
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Where these live, and how well. Stated rather than implied: an
            interface that says "encrypted" while the key sits in a file beside
            the data would be worse than one that says nothing. */}
        <div className="px-3 py-2 border-t border-[var(--border-soft)] text-[10px]
                        text-[var(--text-faint)] leading-relaxed">
          {list?.secure
            ? 'Encrypted on this Mac. The key is in your keychain.'
            : 'Encrypted on this Mac. No keychain was available, so the key is in a '
              + 'file next to them — which protects them if the files are copied '
              + 'away, and not if the whole folder is.'}
          {!!list?.unreadable && (
            <div className="mt-1 text-amber-400/90">
              {list.unreadable} {list.unreadable === 1 ? 'conversation' : 'conversations'} could
              not be decrypted. They were written with a different key.
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
