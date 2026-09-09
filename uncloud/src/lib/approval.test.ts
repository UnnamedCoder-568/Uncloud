/** The 428 handshake.
 *
 *  The engine answers 428 when a person has to decide: nothing was refused,
 *  the call is unfinished. Every surface goes through `api`, so intercepting it
 *  there is what makes one gate cover all of them — and the two ways that goes
 *  wrong are both silent. Without an asker, every gated action fails with a
 *  raw error. With a careless retry, one unanswerable request becomes an
 *  unbreakable loop of prompts.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: async () => ({ port: 1234, token: 'test-token' }),
}));

import { api, setApprovalAsker, type ApprovalAnswer } from './sidecar';

function approvalResponse() {
  return new Response(JSON.stringify({
    detail: {
      approval: {
        action: 'fs_write', category: 'write', summary: 'Write notes.md',
        preview: { path: '/tmp/notes.md' }, origin: 'agent', mode: 'ask',
      },
    },
  }), { status: 428 });
}

function ok(body: unknown = { done: true }) {
  return new Response(JSON.stringify(body), { status: 200 });
}

let calls: string[];

beforeEach(() => {
  calls = [];
});

afterEach(() => {
  setApprovalAsker(null);
  vi.unstubAllGlobals();
});

function stubFetch(responses: Response[]) {
  let n = 0;
  vi.stubGlobal('fetch', async (url: string) => {
    calls.push(String(url));
    return responses[Math.min(n++, responses.length - 1)];
  });
}

describe('the approval handshake', () => {
  it('asks, answers, and repeats the original call', async () => {
    stubFetch([approvalResponse(), ok(), ok({ done: true })]);
    const asked: string[] = [];
    setApprovalAsker(async (request) => {
      asked.push(request.summary);
      return 'yes';
    });

    await expect(api('/api/thing', { method: 'POST' })).resolves.toEqual({ done: true });
    expect(asked).toEqual(['Write notes.md']);
    // The original call, the answer, then the original call again.
    expect(calls.map((c) => c.replace('http://127.0.0.1:1234', ''))).toEqual([
      '/api/thing', '/api/approvals/answer', '/api/thing',
    ]);
  });

  it('gives up after one retry rather than prompting forever', async () => {
    // An engine that keeps returning 428 after an answer has a problem the
    // user cannot fix by clicking again. Looping here would make the
    // application impossible to close.
    stubFetch([approvalResponse()]);
    let asks = 0;
    setApprovalAsker(async () => { asks += 1; return 'yes'; });

    await expect(api('/api/thing')).rejects.toThrow(/428/);
    expect(asks).toBe(1);
  });

  it('surfaces an error rather than hanging when nothing can ask', async () => {
    // During startup there is no prompt mounted. A promise that never settles
    // would look like the application had frozen.
    stubFetch([approvalResponse()]);
    await expect(api('/api/thing')).rejects.toThrow(/428/);
  });

  it('passes a refusal through without repeating the call', async () => {
    stubFetch([approvalResponse(), ok(), new Response('{"detail":"denied"}',
                                                      { status: 403 })]);
    setApprovalAsker(async () => 'no' as ApprovalAnswer);
    await expect(api('/api/thing')).rejects.toThrow(/403/);
  });

  it('leaves an ordinary failure alone', async () => {
    stubFetch([new Response('nope', { status: 500 })]);
    let asked = false;
    setApprovalAsker(async () => { asked = true; return 'yes'; });
    await expect(api('/api/thing')).rejects.toThrow(/500/);
    expect(asked).toBe(false);
  });

  it('ignores a 428 whose body is not an approval', async () => {
    stubFetch([new Response('gateway said no', { status: 428 })]);
    let asked = false;
    setApprovalAsker(async () => { asked = true; return 'yes'; });
    await expect(api('/api/thing')).rejects.toThrow(/428/);
    expect(asked).toBe(false);
  });
});
