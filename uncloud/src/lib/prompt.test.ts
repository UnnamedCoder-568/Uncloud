/** The system prompt is the environment the model reasons inside, and its
 *  ORDER is load-bearing in a way that is easy to regress.
 *
 *  This prompt used to open with "You can show a picture", and a 4B model drew
 *  one for nearly every reply — including questions about episode numbers,
 *  where a picture answers nothing. The restraint was there, as one clause
 *  saying "use it sparingly", and it lost against three sentences of
 *  encouragement placed first.
 */

import { describe, expect, it } from 'vitest';

import { chatSystemPrompt } from './sidecar';

describe('system prompt', () => {
  it('does not mention pictures when the user has them off', () => {
    // The reliable way not to get a picture with every reply is not to
    // describe pictures. A capability a model is told about is one it uses.
    const prompt = chatSystemPrompt({ pictures: false });
    expect(prompt).not.toContain('[[image:');
    expect(prompt).not.toContain('[[pictures:');
  });

  it('puts answering and looking up before drawing', () => {
    const prompt = chatSystemPrompt({ pictures: true });
    expect(prompt.indexOf('Answer directly')).toBeLessThan(prompt.indexOf('[[image:'));
    expect(prompt.indexOf('look things up')).toBeLessThan(prompt.indexOf('[[image:'));
  });

  it('tells the model the date, so it can tell its memory is stale', () => {
    const prompt = chatSystemPrompt({ now: new Date('2026-09-05T12:00:00Z') });
    expect(prompt).toContain('2026');
    expect(prompt).toMatch(/out of date|training finished/);
  });

  it('names the kind of question that should be looked up, not recalled', () => {
    // Episode numbers and titles are reconstructed wrongly with total
    // confidence, and are trivial to check.
    expect(chatSystemPrompt()).toContain('episode numbers');
  });

  it('says plainly that most answers are better with no picture', () => {
    expect(chatSystemPrompt({ pictures: true })).toContain('the default is not to');
  });
});
