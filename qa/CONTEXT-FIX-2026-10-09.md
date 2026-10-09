# Context overflow regression

Reported Windows Gemma request: 4,656–4,808 input tokens against a 1,024-token runtime. The UI showed conversation-only usage. The exact Windows model file and hardware are unavailable on this Mac; do not treat automated checks as target-device reproduction.

Fixed: web evidence is sized using the active native tokenizer and chat template, reserving reply capacity. Original history is never silently truncated. Source URLs survive excerpt shortening. When even conversation plus sources cannot fit, a clear compaction/larger-window message replaces an oversized dispatch. Retained evidence is saved with the user turn and included in subsequent prompt assembly and the meter. This is source-excerpt budgeting, not conversation compaction; existing structured Compact remains separate.

Added: explicit GGUF context-window setting, native-limit validation before unloading, per-model saved preference, resident-model reuse on ordinary turns, actual effective runtime context in engine status, Guide documentation. Memory-based automatic selection remains conservative; explicit larger windows require adequate device memory. No unsupported automatic enlargement or forced optimization flags were added.

Validation: all isolated stages passed (Python lint, frontend lint, backend tests, frontend tests, production build, desktop tests, release metadata). Local backend: 1,010 passed, one skipped; frontend: 131 passed; desktop: four passed. Local backend count includes the owner's unrelated uncommitted legal draft tests, which are excluded from this release. Seven native-engine tests passed again after the final status change.

New regression coverage: oversized evidence plus output reserve, unchanged fitting evidence, authoritative output budgets, unavailable token accounting, saved-source continuity, invalid context rejected before unloading, warm reuse of an explicitly configured model. No speed or broad intelligence improvement is claimed from these tests.

Owner device check: install this release on the reported Windows machine, load the same GGUF, verify its effective context, apply a larger model-supported window if memory permits, retry the web query and a follow-up, and test Compact on a genuinely long conversation. A 1,024-token window cannot hold thousands of tokens of evidence regardless of UI or backend.

References: https://lmstudio.ai/docs/developer/rest/load and https://docs.ollama.com/context-length describe configurable allocation and memory tradeoffs. These settings do not enlarge a model's trained context capability.
