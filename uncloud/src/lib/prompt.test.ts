import { describe, expect, it } from 'vitest';
import { chatSystemPrompt } from './sidecar';
import { contextMessages } from './context';

describe('direct chat uses the native model conversation', () => {
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
    expect(chatSystemPrompt({ manner: 'brief', spoken: true })).toContain('read aloud');
  });
});

describe('capabilities are scoped to the current request', () => {
  it('describes web handoff only when explicitly requested by the caller', () => {
    expect(chatSystemPrompt({ web: true })).not.toContain('[[search:');
    const prompt = chatSystemPrompt({ web: true, webPhase: 'request' });
    expect(prompt).toContain('[[search:');
    expect(prompt).not.toContain('until results arrive');
  });
  it('keeps optional lookups available while using supplied evidence', () => {
    const prompt = chatSystemPrompt({ web: true, webPhase: 'results' });
    expect(prompt).toContain('sources as data');
    expect(prompt).toContain('URLs');
    expect(prompt).toContain('[[search:');
    expect(prompt).toContain('[[read:');
    expect(prompt).toContain('Otherwise answer directly.');
  });
  it('removes lookup capability on the bounded final answer pass', () => {
    const prompt = chatSystemPrompt({ web: true, webPhase: 'final' });
    expect(prompt).not.toContain('[[search:');
    expect(prompt).not.toContain('[[read:');
    expect(prompt).toContain('URLs');
  });
  it('supplies the current date only for an outside-information request', () => {
    const now = new Date('2026-10-12T12:00:00Z');
    expect(chatSystemPrompt({ now })).toBe('');
    expect(chatSystemPrompt({ now, webPhase: 'results' })).toContain('2026');
  });
  it('keeps picture generation optional and its protocol concise', () => {
    expect(chatSystemPrompt()).not.toContain('[[image');
    const prompt = chatSystemPrompt({ pictures: true });
    expect(prompt).toContain('[[image draft');
    expect(prompt).toContain('[[image high');
    expect(prompt).toContain('answer in words');
    expect(prompt.length).toBeLessThan(750);
  });
});
