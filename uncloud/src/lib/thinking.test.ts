/** The splitter has to survive being fed one character at a time, because that
 *  is roughly what a token stream is. */

import { describe, expect, it } from 'vitest';

import { ThinkingSplitter, splitThinking } from './thinking';

/** Feed a whole reply through in chunks of `size`, as a server would. */
function stream(text: string, size: number) {
  const splitter = new ThinkingSplitter();
  const pieces = [];
  for (let i = 0; i < text.length; i += size) {
    pieces.push(...splitter.push(text.slice(i, i + size)));
  }
  pieces.push(...splitter.flush());
  return {
    thinking: pieces.filter((p) => p.kind === 'thinking').map((p) => p.text).join(''),
    answer: pieces.filter((p) => p.kind === 'text').map((p) => p.text).join(''),
  };
}

//: The reply that prompted this, shortened. The model wrote its reasoning into
//  the answer, and the whole thing was shown as the answer.
const REAL = `<think>
The user is asking about "iOS 27 feature list" - but this is impossible.
</think>

iOS 27 does not exist yet. Apple usually announces major iOS updates at Apple
Events, typically in September or June each year.`;

describe('splitting', () => {
  it('takes the reasoning out of the answer', () => {
    const { thinking, answer } = splitThinking(REAL);
    expect(thinking).toContain('The user is asking about');
    expect(answer).toContain('iOS 27 does not exist yet');
    expect(answer).not.toContain('<think>');
    expect(answer).not.toContain('The user is asking about');
  });

  it('leaves a reply with no tags completely alone', () => {
    const plain = 'Just an answer, with an * asterisk and a < less-than.';
    expect(splitThinking(plain)).toEqual({ thinking: '', answer: plain });
  });

  it('handles the other spellings models use', () => {
    for (const tag of ['think', 'thinking', 'thought', 'reasoning']) {
      const { thinking, answer } = splitThinking(`<${tag}>working</${tag}>done`);
      expect(thinking).toBe('working');
      expect(answer).toBe('done');
    }
  });

  it('is not confused by capitals', () => {
    expect(splitThinking('<Think>a</THINK>b').answer).toBe('b');
  });

  it('shows a tag it does not know rather than swallowing the answer', () => {
    const { answer } = splitThinking('<plan>a</plan>b');
    expect(answer).toBe('<plan>a</plan>b');
  });

  it('handles several blocks in one reply', () => {
    const { thinking, answer } = splitThinking('<think>one</think>A<think>two</think>B');
    expect(thinking).toBe('onetwo');
    expect(answer).toBe('AB');
  });
});

describe('streaming', () => {
  it('gives the same result at every chunk size', () => {
    const whole = splitThinking(REAL);
    for (const size of [1, 2, 3, 5, 7, 13, 64, 4096]) {
      expect(stream(REAL, size)).toEqual(whole);
    }
  });

  it('never shows a partial tag as answer text', () => {
    // `<th` arriving alone must be held, not printed and then retracted —
    // the user would see the tag flash up in the middle of the reply.
    const splitter = new ThinkingSplitter();
    const shown = [...splitter.push('Answer <th')]
      .filter((p) => p.kind === 'text').map((p) => p.text).join('');
    expect(shown).toBe('Answer ');
  });

  it('shows a dangling angle bracket once the reply ends', () => {
    // It was never a tag after all, and losing the character would be worse.
    const splitter = new ThinkingSplitter();
    splitter.push('Compare a <');
    const out = [...splitter.flush()];
    expect(out.map((p) => p.text).join('')).toBe('<');
  });

  it('loses nothing, whatever the split', () => {
    const text = 'A<think>B</think>C<thinking>D</thinking>E';
    for (let size = 1; size <= text.length; size++) {
      const { thinking, answer } = stream(text, size);
      expect(answer).toBe('ACE');
      expect(thinking).toBe('BD');
    }
  });

  it('keeps reasoning that never closes as reasoning', () => {
    // A reply cut off mid-thought. It belongs in the collapsed section, not
    // shown as the answer.
    const { thinking, answer } = stream('<think>still going', 3);
    expect(thinking).toBe('still going');
    expect(answer).toBe('');
  });
});
