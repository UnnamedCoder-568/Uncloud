import { expect, it } from 'vitest';
import { fitToolContext, fitWebContext } from './web-context';
import type { ChatMessage } from './sidecar';

const assemble = (text: string): ChatMessage[] => [{ role: 'user', content: `Original intent\n${text}` }];
const count = async (messages: ChatMessage[]) => ({ used: messages[0].content.length, limit: 1024, exact: true });

it('fits oversized evidence including reply reserve, retaining source URLs and intent', async () => {
  const fitted = await fitWebContext(`Source title\nhttps://example.com/source\n${'evidence '.repeat(600)}`, assemble, count);
  expect(fitted.usage.used! + fitted.replyBudget).toBeLessThanOrEqual(1024);
  expect(fitted.evidence).toContain('https://example.com/source');
  expect(fitted.evidence).toContain('"source_excerpt":"partial"');
  expect(assemble(fitted.evidence)[0].content).toContain('Original intent');
});
it('leaves evidence unchanged when the full request fits', async () => {
  const fitted = await fitWebContext('small evidence', assemble, count, 100);
  expect(fitted.evidence).toBe('small evidence');
  expect(fitted.replyBudget).toBe(100);
});
it('bounds a saved ceiling that exceeds the newly selected runtime window', async () => {
  const fitted = await fitWebContext('source', assemble, count, 4096);
  expect(fitted.replyBudget).toBe(1024 - fitted.usage.used!);
  expect(fitted.usage.used! + fitted.replyBudget).toBeLessThanOrEqual(1024);
});

it('does not cap Auto generation to the fraction reserved while fitting evidence', async () => {
  const fitted = await fitWebContext('source', assemble, async () => ({
    used: 2000, limit: 131072, reply_limit: 131072, exact: true,
  }));
  expect(fitted.replyBudget).toBe(129072);
});
it('never drops conversation to make room for outside evidence', async () => {
  const full = (text: string): ChatMessage[] => [{ role: 'user', content: 'intent '.repeat(200) + text }];
  await expect(fitWebContext('source', full, count, 100)).rejects.toThrow('Compact');
});
it('does not guess when native token accounting fails', async () => {
  await expect(fitWebContext('source', assemble, async () => ({ used: null, limit: 1024, exact: false }))).rejects.toThrow('Could not check');
});

it('fits all native tool results together, keeping every call and URL', async () => {
  const calls = ['one', 'two'];
  const assembleBatch = (values: string[]): ChatMessage[] => [
    { role: 'user', content: 'Compare both sources' },
    { role: 'assistant', content: '', tool_calls: calls.map(id => ({ id, type: 'function',
      function: { name: 'web_read', arguments: JSON.stringify({ url: `https://${id}.example` }) } })) },
    ...values.map((content, index) => ({ role: 'tool' as const, tool_call_id: calls[index], content })),
  ];
  const fitted = await fitToolContext(calls.map(id => `Source ${id}\nhttps://${id}.example\n${'Evidence '.repeat(1000)}`),
    assembleBatch, async turns => ({ used: JSON.stringify(turns).length, limit: 2000, exact: true }));
  expect(fitted.evidence[0]).toContain('https://one.example');
  expect(fitted.evidence[1]).toContain('https://two.example');
  expect(assembleBatch(fitted.evidence).slice(2).map(turn => turn.tool_call_id)).toEqual(calls);
  expect(fitted.usage.used! + fitted.replyBudget).toBeLessThanOrEqual(2000);
});

it('can shorten a long single-line result without losing a URL on that line', async () => {
  const fitted = await fitWebContext(`${'text '.repeat(1000)}https://example.com/original`, assemble, count);
  expect(fitted.evidence).toContain('https://example.com/original');
  expect(fitted.usage.used! + fitted.replyBudget).toBeLessThanOrEqual(1024);
});

it('keeps structured search results valid and retains decoded source URLs while fitting', async () => {
  const evidence = JSON.stringify({ results: [{ source: 'Title\nhttps://example.com/source\nSnippet',
    excerpt: 'Source material '.repeat(600), status: 'retrieved' }] });
  const fitted = await fitWebContext(evidence, assemble, count);
  const data = JSON.parse(fitted.evidence);
  expect(data.results[0].source).toContain('https://example.com/source');
  expect(data.results[0].status).toBe('retrieved');
  expect(data.source_excerpt).toBe('partial');
  expect(fitted.usage.used! + fitted.replyBudget).toBeLessThanOrEqual(1024);
});
