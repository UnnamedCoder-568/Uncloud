import { describe, expect, it } from 'vitest';

import { findLookups, resultsTurn, stripLookups } from './lookup';

describe('finding lookups', () => {
  it('finds the plain form', () => {
    expect(findLookups('[[search: iOS 27 features]]'))
      .toEqual([{ kind: 'search', argument: 'iOS 27 features' }]);
  });

  it('finds a read', () => {
    expect(findLookups('[[read: https://apple.com/ios]]'))
      .toEqual([{ kind: 'read', argument: 'https://apple.com/ios' }]);
  });

  it('tolerates the spacing and capitals models actually produce', () => {
    for (const form of ['[[ search : x ]]', '[[Search: x]]', '[[SEARCH:x]]']) {
      expect(findLookups(form)).toEqual([{ kind: 'search', argument: 'x' }]);
    }
  });

  it('finds several, in order', () => {
    expect(findLookups('a [[search: one]] b [[read: http://x]] c').map((l) => l.argument))
      .toEqual(['one', 'http://x']);
  });

  it('asks once when asked twice', () => {
    expect(findLookups('[[search: same]] [[search: SAME]]')).toHaveLength(1);
  });

  it('ignores an empty request', () => {
    expect(findLookups('[[search: ]]')).toEqual([]);
  });

  it('finds nothing in an ordinary answer', () => {
    expect(findLookups('Arrays use [[0]] in some languages. Not a lookup.')).toEqual([]);
  });
});

describe('stripping markers', () => {
  it('takes the plumbing out of the answer', () => {
    expect(stripLookups('Let me check.\n\n[[search: iOS 27]]')).toBe('Let me check.');
  });

  it('does not leave a hole where the marker was', () => {
    expect(stripLookups('Before.\n\n[[search: x]]\n\nAfter.')).toBe('Before.\n\nAfter.');
  });

  it('leaves an answer with no markers untouched', () => {
    expect(stripLookups('Just an answer.')).toBe('Just an answer.');
  });
});

describe('results turn', () => {
  it('labels them as retrieved, not remembered', () => {
    const turn = resultsTurn([{ kind: 'search', argument: 'x' } as never]
      .map((lookup) => ({ lookup, text: 'a result' })));
    expect(turn).toContain('came from the web just now');
    expect(turn).toContain('prefer them over what you remember');
    expect(turn).toContain('a result');
  });

  it('clips a long page so it cannot crowd out the question', () => {
    const turn = resultsTurn([{
      lookup: { kind: 'read', argument: 'http://x' },
      text: 'x'.repeat(20000),
    }]);
    expect(turn.length).toBeLessThan(7000);
    expect(turn).toContain('truncated');
  });
});

describe('picture lookups', () => {
  it('finds the pictures marker', () => {
    expect(findLookups('[[pictures: Frieren anime]]'))
      .toEqual([{ kind: 'pictures', argument: 'Frieren anime' }]);
  });

  it('accepts "images" as the same thing', () => {
    // Models reach for this spelling about as often, and a near miss here is
    // a lookup that silently never happens.
    expect(findLookups('[[images: a red car]]')[0].kind).toBe('pictures');
  });

  it('strips a pictures marker from the answer', () => {
    expect(stripLookups('Here it is.\n\n[[pictures: x]]')).toBe('Here it is.');
  });

  it('does not confuse an image-generation marker for a web lookup', () => {
    // [[image: …]] is the local generator and is handled elsewhere; picking it
    // up here would send every generated illustration to a search engine.
    expect(findLookups('[[image: an invented illustration]]')).toEqual([]);
  });
});
