// Export the actual before/after Chat prompts without opening a browser.
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from '../uncloud/node_modules/typescript/lib/typescript.js';
import { createServer } from '../uncloud/node_modules/vite/dist/node/index.js';

const output = process.argv[2];
if (!output) throw new Error('Provide the output JSON path.');
const root = fileURLToPath(new URL('../', import.meta.url));
const before = execFileSync('git', ['show', 'v0.4.29:uncloud/src/lib/sidecar.ts'], { cwd: root, encoding: 'utf8' });
const declaration = before.slice(before.indexOf('export function chatSystemPrompt('),
  before.indexOf('export interface ReplyImageRequest'));
// Both versions have an empty Plain manner; export only that selected style.
const js = ts.transpileModule(`const MANNERS = [{ id: 'plain', prompt: '' }];\n${declaration}`,
  { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { chatSystemPrompt: oldPrompt } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const server = await createServer({ root: fileURLToPath(new URL('../uncloud/', import.meta.url)),
  configFile: false, server: { middlewareMode: true, hmr: false, ws: false } });
try {
  const { chatSystemPrompt } = await server.ssrLoadModule('/src/lib/sidecar.ts');
  const { resultsTurn } = await server.ssrLoadModule('/src/lib/lookup.ts');
  const options = { web: true, pictures: false, manner: 'plain', now: new Date('2026-10-12T04:30:00Z') };
  const math = 'A bag has 3 red balls and 2 blue balls. Draw two without replacement. What is the probability both are red? Give the exact fraction and one short explanation.';
  const turns = (prompt, text) => [...(prompt ? [{ role: 'system', content: prompt }] : []), { role: 'user', content: text }];
  const deterministic = { reasoning: 'off', temperature: 0, top_p: 1, top_k: 0, presence_penalty: 0, repetition_penalty: 1 };
  const fixture = resultsTurn([{ lookup: { kind: 'search', argument: 'Juniper Z9 specifications' },
    text: 'SYNTHETIC FIXTURE, not a real product. Juniper Z9 has 512 MB RAM and two 2.5 GbE ports. https://example.org/juniper/specifications' }]);
  writeFileSync(output, JSON.stringify([
    { name: 'before_app_prompt', messages: turns(oldPrompt(options), math), inference: deterministic, expected: ['3/10'], expected_probability: '3/10', expected_failure: true },
    { name: 'after_direct', messages: turns(chatSystemPrompt(options), math), inference: deterministic, expected: ['3/10'], expected_probability: '3/10' },
    { name: 'native_baseline', messages: turns('', math), inference: deterministic, native_baseline: true, expected: ['3/10'], expected_probability: '3/10' },
    { name: 'after_direct_repeat', messages: turns(chatSystemPrompt(options), math), inference: deterministic, expected: ['3/10'], expected_probability: '3/10' },
    { name: 'auto_greeting', messages: turns(chatSystemPrompt(options), 'How are we today? Answer in one sentence.'), use_default_output: true,
      inference: {} },
    { name: 'auto_code', messages: turns('', 'Write a Python function named square that returns x multiplied by itself. Return only the code.'), use_default_output: true, expected: ['def square', 'return'] },
    { name: 'high_reasoning', messages: turns('', math), inference: { reasoning: 'high' }, use_default_output: true, expected: ['3/10'], expected_probability: '3/10' },
    { name: 'context_recall', messages: [
      { role: 'user', content: 'Remember: the project is Cedar, the deadline is Tuesday, and the budget is 48 dollars. Never change those constraints.' },
      { role: 'assistant', content: 'Understood.' },
      { role: 'user', content: 'What are the project name, deadline and budget? Answer in one sentence.' },
    ], use_default_output: true, expected: ['Cedar', 'Tuesday', '48'] },
    { name: 'scoped_web_evidence', messages: turns(chatSystemPrompt({ ...options, webPhase: 'results' }),
      'Give the Juniper Z9 RAM and ports, with its source URL.\n\n' + fixture), use_default_output: true,
      expected: ['512', '2.5', 'https://example.org/juniper/specifications'] },
    { name: 'before_app_prompt_warm', messages: turns(oldPrompt(options), math), inference: deterministic,
      expected: ['3/10'], expected_probability: '3/10', expected_failure: true },
  ], null, 2));
} finally {
  await server.close();
}
