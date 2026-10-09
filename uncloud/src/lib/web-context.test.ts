import { expect, it } from 'vitest';
import { fitWebContext } from './web-context';
import type { ChatMessage } from './sidecar';

const assemble = (text: string): ChatMessage[] => [{ role: 'user', content: `Original intent\n${text}` }];
const count = async (messages: ChatMessage[]) => ({ used: messages[0].content.length, limit: 1024, exact: true });

it('fits oversized evidence including reply reserve, retaining source URLs and intent', async () => {
  const fitted = await fitWebContext(`Source title\nhttps://example.com/source\n${'evidence '.repeat(600)}`, assemble, count);
  expect(fitted.usage.used! + fitted.replyBudget).toBeLessThanOrEqual(1024);
  expect(fitted.evidence).toContain('https://example.com/source');
  expect(fitted.evidence).toContain('incomplete');
  expect(assemble(fitted.evidence)[0].content).toContain('Original intent');
});
it('leaves evidence unchanged when the full request fits', async () => {
  const fitted = await fitWebContext('small evidence', assemble, count, 100);
  expect(fitted.evidence).toBe('small evidence');
  expect(fitted.replyBudget).toBe(100);
});
it('preserves an authoritative reply budget and refuses to truncate conversation', async () => {
  await expect(fitWebContext('source', assemble, count, 1024)).rejects.toThrow('Compact');
});
it('does not guess when native token accounting fails', async () => {
  await expect(fitWebContext('source', assemble, async () => ({ used: null, limit: 1024, exact: false }))).rejects.toThrow('Could not check');
});
