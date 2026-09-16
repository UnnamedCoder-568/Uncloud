import { describe, expect, it } from 'vitest';
import { Sentences } from './useTalk';

/** Speaking a reply sentence by sentence is what removes most of the wait in a
 *  conversation. These pin the part that decides when a sentence is finished —
 *  too eager and the voice reads fragments, too patient and the person waits
 *  for the whole paragraph, which is what happened before. */
describe('splitting a reply as it is written', () => {
  it('gives a sentence the moment it is complete', () => {
    const s = new Sentences();
    expect(s.push('The lighthouse stood')).toEqual([]);
    expect(s.push(' at the edge of the cliff. Every')).toEqual([
      'The lighthouse stood at the edge of the cliff.',
    ]);
    expect(s.rest()).toBe('Every');
  });

  it('holds back a fragment too short to speak alone', () => {
    const s = new Sentences();
    // "Yes." on its own is a breath, not a sentence: it waits for what follows.
    expect(s.push('Yes. It rained all week.')).toEqual(['Yes. It rained all week.']);
  });

  it('keeps a decimal point inside the sentence', () => {
    const s = new Sentences();
    expect(s.push('It costs 10.50 in total and arrives Tuesday.')).toEqual([
      'It costs 10.50 in total and arrives Tuesday.',
    ]);
  });

  it('ends on a question, an exclamation or a paragraph break', () => {
    const asked = new Sentences();
    // The short answer after it waits: spoken on its own it would arrive as a
    // clipped syllable between two pauses. It comes out with the rest.
    expect(asked.push('Is that right? Yes indeed.')).toEqual(['Is that right?']);
    expect(asked.rest()).toBe('Yes indeed.');

    expect(new Sentences().push('Here is the plan\n\nIt starts tomorrow.')).toEqual([
      'Here is the plan', 'It starts tomorrow.',
    ]);
    expect(new Sentences().push('Stop! There is a car coming.')).toEqual([
      'Stop! There is a car coming.',
    ]);
  });

  it('returns whatever is left when the reply ends without punctuation', () => {
    const s = new Sentences();
    s.push('No full stop here');
    expect(s.rest()).toBe('No full stop here');
    expect(s.rest()).toBe('');
  });
});
