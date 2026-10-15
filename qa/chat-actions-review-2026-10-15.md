# Chat presentation and Chisel regression check — 2026-10-15

## Scope

Keep Copy, Note and Chisel quiet until the answer is hovered, with consistent
spacing between user messages and model answers. Preserve the distinct Chisel
tool-execution path. Review streamed answer rendering without loading another
model or operating the owner's Chrome session.

## Changes and evidence

- Desktop pointer: only the hovered answer's action row is revealed. Keyboard
  focus reveals the containing row. On touch, controls remain available.
- The toolbar floats in the normal 40 px gap between messages, without adding
  an empty row to the answer. Padding bridges the pointer path to the controls.
  The same gap applies before and after an answer. On narrow screens, the gap
  is 56 px to clear the existing 44 px touch controls. Bottom padding leaves
  the last toolbar accessible above the composer.
- Bounding boxes for both answers, the intervening user message and both
  action rows were identical before/after hover and focus: **0 px movement**.
- A separate renderer defect was reproduced: the mounted code block and its
  Copy action held the first streamed chunk. Before: two failing, two passing
  component tests. After: all four pass. Unedited blocks now follow their
  source; an explicitly edited working copy is preserved.
- Message keys include the conversation identity so a working copy or expanded
  reasoning state cannot carry into a different saved conversation's same row.
- Chisel's production planner, execution, prompts and permission policies were
  not changed. Added regression tests feed a mocked model plan through the real
  executor, real workspace file tools and real permission gate. Approval writes
  a Python file and reads back identical content; denial leaves no file and
  blocks the dependent verification. Fenced Python alone is rejected as a plan
  and is not represented as completed file work.
- Updated the Guide and patched `source-map-js` from 1.2.1 to 1.2.2 for
  [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).
  `happy-dom` is a development-only dependency for DOM component tests; it is
  not installed into the shipped inference engine.

## Checks

- Exact staged release source, isolated from unrelated local edits and real
  user state: **1,090 backend tests passed, 3 skipped**.
- Frontend: **152 tests / 20 files passed**; lint and production build passed.
- Desktop shell: **5 tests passed**; release-resource checks and Python lint
  passed. The npm dependency audit reports zero known advisories.
- Focused native context, fast-path, reasoning, conversation and runtime tests:
  **65 passed** using mocked backends and temporary state.
- Focused Chisel planning, permissions, computer input, preview and composed
  workflows: **87 passed**, including the three new coding execution cases.
- Real browser CSS fixture: desktop idle, hover, unhover, keyboard focus/blur,
  adjacent-message isolation, pointer access to controls, equal message gaps,
  touch access and narrow-screen overflow passed.
  [Measured boxes](chat-actions-2026-10-15/results.json),
  [idle](chat-actions-2026-10-15/desktop-idle.png),
  [hover](chat-actions-2026-10-15/desktop-hover.png),
  [touch](chat-actions-2026-10-15/touch.png).
  Reproduce with `python qa/check-chat-actions.py` while the isolated Vite
  preview runs at `127.0.0.1:1437`; the script requires Playwright and its
  installed Chromium test browser, and never attaches to a user profile.

## Boundaries

The isolated browser fixture uses the actual application stylesheet and message
structure. It does not prove every native WebView interaction. The Chisel
tests verify execution and permissions for supplied model plans; they do not
guarantee that every checkpoint chooses the right tools. No native generation
speed, model intelligence or summarization quality claim is made in this
presentation release. No user model was stopped or loaded by these tests.

Context and Compact behavior is unchanged: the effective context window is
measured in tokens, and Compact is offered at 75%. The supplied screenshot's
6,556 / 57,344 tokens is about 11.4%; its 75% threshold is 43,008 tokens.
Compaction preserves original saved history and replaces earlier active context
with inspectable memory plus recent turns. Summarization is not lossless, so
important retained details should be inspected before relying on them.
