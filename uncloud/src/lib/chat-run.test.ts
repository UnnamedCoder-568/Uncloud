import { describe, expect, it, vi } from 'vitest';
import { ApiError, CHAT_STALL_MS, chatRunStalled, isUnloadedModelError, streamChat, wireMessage } from './sidecar';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn(async () => ({ port: 1234, token: 'test-token' })) }));

describe('chat run progress', () => {
  it('sends identical clean model requests from desktop and paired web clients', async () => {
    const requests: { body: unknown; options: RequestInit }[] = [];
    vi.stubGlobal('fetch', async (_url: string, options: RequestInit = {}) => {
      if (options.method === 'POST') {
        requests.push({ body: JSON.parse(String(options.body)), options });
        return new Response(JSON.stringify({ id: 'run', status: 'running', frames: [], cursor: 0 }));
      }
      expect(options.cache).toBe('no-store');
      return new Response(JSON.stringify({ id: 'run', status: 'done', cursor: 1,
        frames: [JSON.stringify({ choices: [{ delta: { content: 'Test response.' } }] })] }));
    });
    try {
      for (const desktop of [true, false]) {
        vi.stubGlobal('window', desktop ? { __TAURI_INTERNALS__: {} } : {});
        for await (const _chunk of streamChat([{ role: 'user', content: 'What is your model name?' }],
          undefined, undefined, { path: '/selected/model', engine: 'gguf', webTools: true, chartTools: true })) { /* Drain. */ }
      }
      expect(requests[0].body).toEqual(requests[1].body);
      expect(requests[1].body).toMatchObject({ inherit_defaults: false, inference: {},
        model_path: '/selected/model', web_tools: true, chart_tools: true,
        messages: [{ role: 'user', content: 'What is your model name?' }] });
      expect(requests[0].options.headers).toMatchObject({ Authorization: 'Bearer test-token' });
      expect(requests[1].options.headers).not.toHaveProperty('Authorization');
      expect(requests.every(request => request.options.cache === 'no-store')).toBe(true);
    } finally { vi.unstubAllGlobals(); }
  });
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
  it('forwards native calls and matching outputs without application metadata', () => {
    const calls = [{ id: 'a', type: 'function' as const,
      function: { name: 'web_search', arguments: '{"query":"Neptune"}' } }];
    expect(wireMessage({ role: 'assistant', content: '', reasoning: 'private', tool_calls: calls }))
      .toEqual({ role: 'assistant', content: '', tool_calls: calls });
    expect(wireMessage({ role: 'tool', content: 'Source', tool_call_id: 'a' }))
      .toEqual({ role: 'tool', content: 'Source', tool_call_id: 'a' });
  });
  it('assembles native streaming calls only after the backend finishes', async () => {
    const requests: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', async (_url: string, options: RequestInit = {}) => {
      if (options.method === 'POST') {
        requests.push(JSON.parse(String(options.body)));
        return new Response(JSON.stringify({ id: 'run', status: 'running', frames: [], cursor: 0 }));
      }
      return new Response(JSON.stringify({ id: 'run', status: 'done', cursor: 2, frames: [
        JSON.stringify({ choices: [{ delta: { tool_calls: [{ index: 0, id: 'a',
          function: { name: 'web_search', arguments: '{"query":"Nep' } }] } }] }),
        JSON.stringify({ choices: [{ finish_reason: 'tool_calls', delta: {
          tool_calls: [{ index: 0, function: { arguments: 'tune"}' } }] } }] }),
      ] }));
    });
    try {
      const chunks = [];
      for await (const chunk of streamChat([{ role: 'user', content: 'Find Neptune' }],
        undefined, undefined, { path: '/test', engine: 'mlx-vlm', webTools: true })) chunks.push(chunk);
      expect(requests[0]).toMatchObject({ web_tools: true,
        messages: [{ role: 'user', content: 'Find Neptune' }] });
      expect(chunks).toEqual([{ kind: 'tool_calls', text: '', tool_calls: [{ id: 'a', type: 'function',
        function: { name: 'web_search', arguments: '{"query":"Neptune"}' } }] }]);
    } finally { vi.unstubAllGlobals(); }
  });
});
