import { describe, expect, it } from 'vitest';
import { CHAT_STALL_MS, chatRunStalled } from './sidecar';

describe('chat run progress', () => {
  it('allows slow local inference before the inactivity limit', () => {
    expect(chatRunStalled(1_000, 1_000 + CHAT_STALL_MS - 1)).toBe(false);
  });

  it('stops a run that has produced no frames for two minutes', () => {
    expect(chatRunStalled(1_000, 1_000 + CHAT_STALL_MS)).toBe(true);
  });
});
