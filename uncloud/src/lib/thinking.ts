/** Separating a model's thinking from its answer.
 *
 *  Well-behaved servers put the chain of thought in `reasoning_content` and the
 *  answer in `content`, and the interface can collapse one and show the other.
 *  Plenty of models do not: they write `<think>…</think>` into the answer
 *  itself, because the tag is part of what they were trained to emit and the
 *  server passes it straight through.
 *
 *  Unsplit, the reasoning is shown as though it were the reply — the reader
 *  gets several paragraphs of the model talking to itself, in which it may
 *  well contradict the answer that follows, before reaching the answer.
 *
 *  This is a state machine rather than a regular expression because the text
 *  arrives a token at a time. `<think>` routinely arrives as `<th` then `ink>`,
 *  and a partial tag must be held back rather than printed and then retracted.
 */

//: The spellings in use. Matched case-insensitively; a model that invents its
//  own tag will have it shown, which is the safe direction — an unknown tag
//  printed is a curiosity, an answer swallowed is a bug.
const NAMES = ['think', 'thinking', 'thought', 'reason', 'reasoning'];

const OPEN = NAMES.map((n) => `<${n}>`);
const CLOSE = NAMES.map((n) => `</${n}>`);

export interface Piece {
  kind: 'thinking' | 'text';
  text: string;
}

/** The longest suffix of `text` that could still become one of `tags`.
 *
 *  This is the whole trick. At the end of a chunk, `…answer <thi` might be the
 *  start of a tag or might be literal text, and there is no way to know until
 *  more arrives. That suffix is held; everything before it is safe to emit.
 */
function danglingFrom(text: string, tags: string[]): number {
  const limit = Math.min(text.length, Math.max(...tags.map((t) => t.length)) - 1);
  for (let take = limit; take > 0; take--) {
    const tail = text.slice(text.length - take).toLowerCase();
    if (tags.some((tag) => tag.startsWith(tail))) return take;
  }
  return 0;
}

function findFirst(haystack: string, needles: string[]): { at: number; tag: string } | null {
  const lower = haystack.toLowerCase();
  let best: { at: number; tag: string } | null = null;
  for (const needle of needles) {
    const at = lower.indexOf(needle);
    if (at !== -1 && (!best || at < best.at)) best = { at, tag: needle };
  }
  return best;
}

/** Splits a stream of text into thinking and answer.
 *
 *  One instance per reply. `push` returns what is safe to show now; `flush`
 *  returns whatever was being held when the stream ended, so a reply that stops
 *  mid-tag still shows its last few characters rather than losing them.
 */
export class ThinkingSplitter {
  private held = '';
  private inside = false;

  push(chunk: string): Piece[] {
    this.held += chunk;
    const out: Piece[] = [];

    for (;;) {
      if (this.inside) {
        const close = findFirst(this.held, CLOSE);
        if (close) {
          const body = this.held.slice(0, close.at);
          if (body) out.push({ kind: 'thinking', text: body });
          this.held = this.held.slice(close.at + close.tag.length);
          this.inside = false;
          continue;
        }
        // Still thinking. Emit all but a possible partial closing tag.
        const keep = danglingFrom(this.held, CLOSE);
        const ready = this.held.slice(0, this.held.length - keep);
        if (ready) out.push({ kind: 'thinking', text: ready });
        this.held = this.held.slice(this.held.length - keep);
        return out;
      }

      const open = findFirst(this.held, OPEN);
      if (open) {
        const before = this.held.slice(0, open.at);
        if (before) out.push({ kind: 'text', text: before });
        this.held = this.held.slice(open.at + open.tag.length);
        this.inside = true;
        continue;
      }

      const keep = danglingFrom(this.held, OPEN);
      const ready = this.held.slice(0, this.held.length - keep);
      if (ready) out.push({ kind: 'text', text: ready });
      this.held = this.held.slice(this.held.length - keep);
      return out;
    }
  }

  /** Whatever is still held. A dangling `<` at the end of a reply is text. */
  flush(): Piece[] {
    if (!this.held) return [];
    const piece: Piece = { kind: this.inside ? 'thinking' : 'text', text: this.held };
    this.held = '';
    return [piece];
  }
}

/** The same split, for text that is already complete. Used when a saved
 *  conversation is reopened: it was stored as the model wrote it. */
export function splitThinking(text: string): { thinking: string; answer: string } {
  const splitter = new ThinkingSplitter();
  const pieces = [...splitter.push(text), ...splitter.flush()];
  return {
    thinking: pieces.filter((p) => p.kind === 'thinking').map((p) => p.text).join(''),
    answer: pieces.filter((p) => p.kind === 'text').map((p) => p.text).join(''),
  };
}
