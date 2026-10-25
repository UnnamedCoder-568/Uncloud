// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { InteractionProvider } from '../lib/interactions';
import type { Interaction, NotificationReport } from '../lib/interactions';
import NotificationCenter from './NotificationCenter';
import PendingInteractions from './PendingInteractions';

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../lib/sidecar', () => ({ api: client.get, apiPost: client.post }));
vi.mock('../lib/platform', () => ({ inDesktop: () => false }));
const permission: Interaction = {
  id: 'permission-1', run_id: 'current-task', kind: 'permission', status: 'pending',
  expires: Date.now() / 1000 + 300,
  details: { summary: 'Run Python code', preview: { code: 'print("<b>literal</b>")', cwd: '/test' } },
};
let report: NotificationReport;
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  report = { events: [], requests: [structuredClone(permission)], runs: [],
    preferences: { enabled: true, sound: false, system_sound: false, background: true,
      quiet: false, categories: {} } };
  client.get.mockImplementation(async () => structuredClone(report));
  client.post.mockImplementation(async () => { report.requests = []; return {}; });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});
async function mount() {
  await act(() => root.render(<InteractionProvider>
    <PendingInteractions /><NotificationCenter navigate={vi.fn()} />
  </InteractionProvider>));
}
const buttons = (text: string) => [...container.querySelectorAll('button')]
  .filter(button => button.textContent === text);
const bell = () => container.querySelector<HTMLButtonElement>('[title="Notifications and requests"]')!;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

it('shows an actionable approval without opening the tray and shares one decision across both surfaces', async () => {
  await mount();
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(buttons('Allow this action')).toHaveLength(1);
  expect(container.textContent).toContain('print("<b>literal</b>")');
  expect(container.querySelector('b')).toBeNull();
  expect(client.post).not.toHaveBeenCalled();
  await act(() => bell().click());
  expect(buttons('Allow this action')).toHaveLength(2);
  const decision = deferred<object>();
  client.post.mockImplementationOnce(() => decision.promise);
  await act(() => { for (const button of buttons('Allow this action')) button.click(); });
  expect(client.post).toHaveBeenCalledExactlyOnceWith('/api/interactions/permission-1/answer', { answer: 'yes' });
  expect(buttons('Deny').every(button => button.disabled)).toBe(true);
  report.requests = [];
  await act(() => decision.resolve({}));
  expect(container.querySelectorAll('[aria-label="Action approval"]')).toHaveLength(0);
});

it('can deny inline without changing standing permissions', async () => {
  await mount();
  await act(() => buttons('Deny')[0].click());
  expect(client.post).toHaveBeenCalledExactlyOnceWith('/api/interactions/permission-1/answer', { answer: 'no' });
  expect(buttons('Allow this action')).toHaveLength(0);
});

it('shows expiry errors and never retries an old approval automatically', async () => {
  await mount();
  client.post.mockImplementationOnce(async () => {
    report.requests[0].status = 'expired';
    throw new Error('This request is no longer active. Review the task and run it again.');
  });
  await act(() => buttons('Allow this action')[0].click());
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('no longer active');
  expect(buttons('Allow this action')).toHaveLength(0);
  expect(client.post).toHaveBeenCalledTimes(1);
});

it('does not restore an answered request from an older notification refresh', async () => {
  await mount();
  const stale = deferred<NotificationReport>();
  const oldReport = structuredClone(report);
  client.get.mockImplementationOnce(() => stale.promise);
  await act(() => bell().click());
  await act(() => buttons('Allow this action')[0].click());
  expect(buttons('Allow this action')).toHaveLength(0);
  await act(() => stale.resolve(oldReport));
  expect(buttons('Allow this action')).toHaveLength(0);
});

it('shows task questions inline and sends only the selected answer', async () => {
  report.requests = [{ ...permission, id: 'question-1', kind: 'question', details: {
    question: 'Which folder?', options: ['Workspace', 'Choose another'] } }];
  await mount();
  expect(container.querySelector('[aria-label="Your answer"]')).not.toBeNull();
  expect(buttons('Reply and continue')[0].disabled).toBe(true);
  await act(() => buttons('Workspace')[0].click());
  expect(client.post).toHaveBeenCalledExactlyOnceWith('/api/interactions/question-1/answer', { answer: 'Workspace' });
});
