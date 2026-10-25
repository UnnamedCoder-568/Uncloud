import { expect, it } from 'vitest';
import { formatToolOutput } from './tool-output';

it('preserves literal paths, source characters, and line breaks in tool text', () => {
  const output = 'C:\\reports\\verification_report.txt\nalpha_beta *literal* <script>';
  expect(formatToolOutput(output)).toBe(output);
});

it('decodes process stdout while retaining output metadata', () => {
  const output = JSON.stringify({ stdout: 'Total: 10\nOK\n',
    outputs: [{ path: '/reports/verification_report.txt', bytes: 188 }] });
  const shown = formatToolOutput(output);
  expect(shown).toContain('Total: 10\nOK\n');
  expect(shown).toContain('/reports/verification_report.txt');
  expect(shown).toContain('188');
});
