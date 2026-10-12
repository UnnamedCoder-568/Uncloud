import { describe, expect, it } from 'vitest';
import { ApiError, CHAT_STALL_MS, chatRunStalled, isUnloadedModelError } from './sidecar';

describe('chat run progress', () => {
  it('allows slow local inference before the inactivity limit', () => {
    expect(chatRunStalled(1_000, 1_000 + CHAT_STALL_MS - 1)).toBe(false);
  });

  it('stops a run that has produced no frames for two minutes', () => {
    expect(chatRunStalled(1_000, 1_000 + CHAT_STALL_MS)).toBe(true);
  });
  it('does not restart a model for an agent-busy conflict or inference failure', () => {
    expect(isUnloadedModelError(new ApiError('A saved agent is running. Pause it in Chisel first.', 409))).toBe(false);
    expect(isUnloadedModelError(new ApiError('Reply budget must leave room for input.', 422))).toBe(false);
    expect(isUnloadedModelError(new ApiError('Load the selected text model to continue.', 409))).toBe(true);
  });
});
