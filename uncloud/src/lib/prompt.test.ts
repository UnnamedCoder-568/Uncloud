import { describe, expect, it } from 'vitest';
import { chatSystemPrompt } from './sidecar';
import { contextMessages } from './context';

describe('direct chat uses the native model conversation', () => {
  it('never adds a date or web instructions in any lookup phase', () => {
    for (const webPhase of ['request', 'results', 'final'] as const) {
      expect(chatSystemPrompt({ web: true, webPhase, pictures: false })).toBe('');
    }
  });
  it('adds no application identity, date, tools or default system prompt', () => {
    for (const web of [true, false]) {
      const prompt = chatSystemPrompt({ web, manner: 'plain' });
      expect(prompt).toBe('');
      const turns = [{ role: 'user' as const, content: 'How are we today?' }];
      expect(contextMessages(turns, prompt)).toEqual(turns);
    }
  });
  it('never describes the software or other application modes to the model', () => {
    for (const webPhase of ['request', 'results', 'final'] as const) {
      const prompt = chatSystemPrompt({ web: true, webPhase, pictures: true });
      expect(prompt).not.toMatch(/Uncloud|Chisel|Chat settings|local assistant/);
    }
  });
  it('never injects a saved voice manner into typed chat', () => {
    const prompt = chatSystemPrompt({ web: false, manner: 'brief' });
    expect(prompt).toBe('');
    expect(chatSystemPrompt({ manner: 'butler' })).toBe('');
  });
  it('uses a spoken manner only for an explicitly spoken response', () => {
    expect(JSON.parse(chatSystemPrompt({ manner: 'brief', spoken: true })).output).toBe('speech');
  });
});

describe('capabilities are scoped to the current request', () => {
  it('does not add application prose for tools, results or the date', () => {
    for (const webPhase of ['request', 'results', 'final'] as const) {
      expect(chatSystemPrompt({ web: true, webPhase,
        now: new Date('2026-10-15T12:00:00Z') })).toBe('');
    }
  });
  it('keeps picture generation optional and its protocol concise', () => {
    expect(chatSystemPrompt()).not.toContain('[[image');
    const prompt = chatSystemPrompt({ pictures: true });
    expect(prompt).toContain('[[image draft');
    expect(prompt).toContain('[[image high');
    expect(JSON.parse(prompt).media.dimensions).toEqual({ min: 256, max: 2048, step: 64 });
    expect(prompt.length).toBeLessThan(750);
  });
});
