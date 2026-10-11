Thinking effort now reserves space for the answer on supported runtimes instead of letting reasoning consume the entire reply allowance. Chat and Chisel expose an accessible effort slider using the selected model/backend's discovered controls. Explicit overrides remain visible and authoritative. Unsupported controls are not simulated.

Web lookup removes the conflicting stop-and-wait instruction, fetches ordinary specification queries before answering, deduplicates completed queries and bounds fallback lookup rounds. Private reasoning never executes tools. Qwen3.5 9B's verified architecture receives the publisher's sampling recommendations when local metadata and user overrides do not supply them.

Downloads now display cumulative progress for the whole pinned model revision, show the active file, preserve completed shards when resuming and validate transfer ranges and file sizes. A completed shard is no longer presented as a completed model. Incomplete folders remain unavailable for inference. The Guide explains the updated controls and download behavior.

Validated with 1,086 backend tests (one skipped), 146 frontend tests, production builds and release-resource checks. Sequential Apple Silicon tests with the same Qwen3.5 9B Q4 model completed source-backed High-effort answers and a correct one-sentence Maximum-effort probability answer. Cancellation and the following request worked. No concurrent model tests or Chrome interaction were used.

Two Maximum-effort raw-model tests still rambled and reached their output ceiling; those failures remain recorded. No universal output-quality or speed improvement is claimed. Gemma's incomplete download was preserved; native Gemma VLM and Windows/Linux generation were not tested on this Mac. Capability, payload, tokenizer-counting and packaging checks cover those paths separately.

The investigation, measured timings and remaining limitations are in [qa/reasoning-effort-audit-2026-10-11.md](https://github.com/UnnamedCoder-568/Uncloud/blob/main/qa/reasoning-effort-audit-2026-10-11.md). Existing context management, compaction, notifications and agent safeguards remain included.
