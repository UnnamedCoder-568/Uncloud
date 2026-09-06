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

describe('the web switch', () => {
  it('describes the capability when it is on', () => {
    expect(chatSystemPrompt({ web: true })).toContain('[[search:');
  });

  it('says plainly that it is offline when it is off', () => {
    // A model that does not know it cannot check will answer questions about
    // the present from memory in the same confident voice it uses for
    // arithmetic. Silence here is how the iOS answer happened.
    const prompt = chatSystemPrompt({ web: false });
    expect(prompt).not.toContain('[[search:');
    expect(prompt).toContain('no internet access');
    expect(prompt).toContain('Never imply you have checked anything');
  });

  it('is on unless asked otherwise', () => {
    expect(chatSystemPrompt()).toContain('[[search:');
  });
});

describe('pictures never replace the answer', () => {
  it('tells the model to write words as well', () => {
    // Its whole reply was "[[image: …]]" and nothing else. The marker is
    // stripped before display, so the message arrived empty — which reads as
    // the application losing the answer rather than the model never writing one.
    const prompt = chatSystemPrompt({ pictures: true });
    expect(prompt).toContain('ALWAYS WRITE YOUR ANSWER IN WORDS');
    expect(prompt).toContain('never the answer');
  });

  it('scopes "stop and write nothing else" to lookups only', () => {
    // That instruction sat directly above the picture markers, and the model
    // read it as covering them too.
    const prompt = chatSystemPrompt({ pictures: true, web: true });
    const stop = prompt.indexOf('STOP and write nothing else');
    expect(stop).toBeGreaterThan(-1);
    expect(prompt.slice(stop, stop + 400)).toContain('never to pictures');
  });
});
