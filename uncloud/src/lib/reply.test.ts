import { describe, expect, it } from 'vitest';
import { cleanReply } from './reply';
import { parseReplyImages } from './sidecar';

describe('cleanReply', () => {
  it('removes lookup, draft-image, and model control protocol', () => {
    expect(cleanReply('Hi\n[[search: cats]]\n[[image: a cat]]\n'
      + '[[image high 1536x1024: a polished cat]]\n<|eot_id|>')).toBe('Hi');
  });

  it('hides a partial marker while a response is streaming', () => {
    expect(cleanReply('Answer\n[[sear', true)).toBe('Answer');
    expect(cleanReply('Answer\n[[search: ca', true)).toBe('Answer');
    expect(cleanReply('Answer\n[[image high 1536x', true)).toBe('Answer');
  });

  it('does not reinterpret ordinary brackets', () => {
    expect(cleanReply('Use [[index]] in the example.')).toBe('Use [[index]] in the example.');
  });
});

describe('reply image instructions', () => {
  it('keeps the legacy instruction as a quick square draft', () => {
    expect(parseReplyImages('[[image: a cat astronaut]]')).toEqual([
      { prompt: 'a cat astronaut', quality: 'draft', width: 512, height: 512 },
    ]);
  });

  it('lets the model request a high-quality render at explicit dimensions', () => {
    expect(parseReplyImages('[[image high 1536x1024: cinematic moon base]]')).toEqual([
      { prompt: 'cinematic moon base', quality: 'high', width: 1536, height: 1024 },
    ]);
  });

  it('bounds unsafe hallucinated dimensions to the Image workspace limits', () => {
    expect(parseReplyImages('[[image high 99999x2: still sensible]]')).toEqual([
      { prompt: 'still sensible', quality: 'high', width: 2048, height: 256 },
    ]);
  });
});
