// Export the production frontend prompt and evidence wrapper for native checks.
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer } from '../uncloud/node_modules/vite/dist/node/index.js';

const output = process.argv[2];
if (!output) throw new Error('Provide the output JSON path.');
const server = await createServer({ root: fileURLToPath(new URL('../uncloud/', import.meta.url)),
  configFile: false, server: { middlewareMode: true, hmr: false, ws: false } });
try {
  const { chatSystemPrompt } = await server.ssrLoadModule('/src/lib/sidecar.ts');
  const { resultsTurn } = await server.ssrLoadModule('/src/lib/lookup.ts');
  const now = new Date('2026-10-11T04:49:00Z');
  const question = 'Ok. So, Juniper Z9. tell me the specs';
  const text = 'SYNTHETIC TEST FIXTURE, not a real product. Official fixture specs: Juniper Z9 router; Wi-Fi 7; three bands (2.4/5/6 GHz); two 2.5 GbE ports; 512 MB RAM. Source: https://example.org/juniper/specifications';
  const evidence = resultsTurn([{ lookup: { kind: 'search', argument: question }, text }]);
  const messages = (phase, user, web = true) => [
    { role: 'system', content: chatSystemPrompt({ now, web, webPhase: phase }) },
    { role: 'user', content: user },
  ];
  const expected = ['512', '2.5', 'https://example.org/juniper/specifications'];
  const native = { temperature: 0, top_p: 1, top_k: 0, presence_penalty: 0, repetition_penalty: 1 };
  writeFileSync(output, JSON.stringify([
    { name: 'lean_evidence_native_sampling', messages: messages('results', question + '\n\n' + evidence), inference: native, expected },
    { name: 'lean_evidence_model_profile', messages: messages('results', question + '\n\n' + evidence), expected },
    { name: 'fallback_web_handoff', messages: messages('request', 'Ok. So, iPhone 18. tell me the specs'), expected: ['[[search:'] },
    { name: 'final_answer_after_duplicate', messages: messages('final', question + '\n\n' + evidence), expected },
    { name: 'unverified_specs_remain_unverified', messages: messages('results', 'Tell me the specifications for the simulated Aurora Q19 product.\n\n' + resultsTurn([
      { lookup: { kind: 'search', argument: 'Aurora Q19' }, text: 'Fixture source https://example.org/aurora. Release is confirmed, but the manufacturer has not published memory, battery, or display specifications. Those specifications are unverified.' },
    ])), expected: ['https://example.org/aurora', 'unverified'] },
  ], null, 2));
} finally {
  await server.close();
}
