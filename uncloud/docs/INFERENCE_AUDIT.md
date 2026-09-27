# Local inference audit — v0.4.13

This is a measured first pass, not a completed audit of every supported model and device. Measurements below use the same resident MiniCPM5 2B 8-bit MLX checkpoint on this Apple Silicon Mac. No weights were downloaded or trained. GGUF, CUDA, Windows, Linux and other model families still need equivalent live runs.

## Current path

Normal Chat assembles its small system prompt, retained conversation and user input, then submits a chat run. The sidecar validates the resident model identity in memory, builds the native payload, sends it over a reused HTTP connection and forwards backend tokens through an event-driven reconnectable stream. The backend owns native template rendering, tokenization, prefill, prefix caching and generation.

Web research and picture generation run only when enabled/requested. Agent planning, tool execution and approval remain in Chisel rather than being mandatory stages of direct chat. The developer direct-model mode bypasses the application system prompt, web/picture features and compacted memory for baseline comparisons.

## Unnecessary work found and removed

- Per-request library scan to rediscover the active model profile: cache it at model load. The reconstructed old path measured roughly 100–150 ms per scan in this library.
- New HTTP client for every ordinary chat request: reuse a pooled asynchronous client.
- Fixed 180 ms frontend polling interval: await a frame event and return immediately.
- Warm-turn readiness request: submit directly; recover an unloaded/mismatched model once through a specific 409 response.
- Re-reading model metadata for inference defaults: load recommendations once with the active model.
- Long ordinary-chat instructions: reduced the no-Web prompt from 1,296 to 591 characters before further context is added. No extra model routing pass was introduced.
- Backend stdout was piped without continuous draining: drain into a bounded log tail so a full pipe cannot block generation.

No normal-turn directory scan, project retrieval, general orchestration model or unused tool schema is injected by this direct-chat path. Conversation persistence remains intentional disk I/O after generation. The optional context meter initializes its native tokenizer outside the send path and caches it; therefore this is not a claim that the entire application performs zero disk I/O.

## Latency evidence

The repeatable transport test uses identical messages, temperature 0, seed 42 and output budget across direct, reconstructed legacy and optimized paths. The legacy path reproduces the former scan/client/polling behavior; it is not an old packaged binary. See `benchmarks/minicpm-transport.json` for every reply, backend usage, timing and configuration fingerprint.

Median warm first-token latency across four controlled prompts:

| Path | Median |
| --- | ---: |
| Direct native HTTP | 98.4 ms |
| Reconstructed legacy | 305.2 ms |
| Optimized sidecar | 103.3 ms |

The optimized path was about 202 ms faster than the reconstructed legacy path in this small sample. First token includes reasoning tokens; time to a completed answer can be much longer. This measurement excludes browser rendering and the incoming frontend-to-sidecar HTTP hop, and is not an end-to-end sub-500 ms guarantee.

Diagnostics expose prompt-payload build, dispatch, backend headers, first token, total time, sampling, and backend usage/timings when supplied. Tokenizer/template, model load, prefill, cache reuse, kernel initialization, memory and sustained generation speed are not separately established here. They must not be reported as zero-cost or improved without backend instrumentation.

## Intelligence issues and fixes

- Global sampling overrides could disregard a model's recommendations. Read native generation/GGUF sampling metadata and per-model overrides; unspecified sampling remains backend-owned. User temperature takes precedence.
- Balanced direct chat no longer silently disables the model's native thinking format or introduces extra reasoning passes.
- MLX's native 512-token output fallback can exhaust itself in reasoning. Use model `max_new_tokens` where provided, otherwise reserve one quarter of the effective runtime context for output. This is a visible runtime policy, not a claimed model recommendation. Chat settings expose an authoritative per-model reply budget. Length-limited responses are explicitly reported, and cannot silently become saved compacted memory.
- Transformers can return a mapping rather than a list of token IDs. Counting mapping fields produced a nonsensical token count. Count IDs, and use MLX's actual tokenizer wrapper so its thinking-prefix tokens match the server.
- Unstructured compacted memory mixed superseded and current decisions. The shared compaction instruction now separates current facts, constraints, open tasks and references; it replaces superseded values and removes completed tasks.

## Context and compaction

Context capability is read from GGUF or MLX configuration and bounded by a conservative local KV-memory estimate. GGUF receives that context setting at launch. MLX's displayed limit is an application memory estimate, not a backend-enforced guarantee; unfamiliar cache layouts and extended-RoPE models need additional validation. Unknown metadata uses an explicitly identified fallback rather than claiming a native maximum.

The bottom-right meter uses native-template token accounting; Compact appears at 75%. Original messages remain encrypted and inspectable. Compaction sends previous memory plus only newly uncompacted turns, retains recent turns, and checks that the result actually reduces token use before saving it. Unknown counts and truncated summaries fail without replacing original history.

The live quality fixture and results are in `benchmarks/minicpm-quality-context.json`. It tests arithmetic, logic, ordering, code reasoning, updated instructions, unsupported facts, full conversation recall, real model-generated compaction, and incremental compaction. Strict formatting and factual correctness are reported separately. This is a small regression fixture, not a general intelligence benchmark or a full 131k-window stress test.

Live results: each path passed all six factual reasoning/instruction cases. Full-context recall preserved 10 of 11 fields but incorrectly grouped tasks and treated a reference as a task. First compaction reduced the prompt from 2,254 to 320 tokens (85.8%) and all 11 checked fields were correct on every path. A second compaction retained unchanged constraints, updated Tuesday to Wednesday, and removed the completed migration-approval task; all fields again passed on every path. The corrected native counter matched backend prompt usage. These results do not establish performance on other models or guarantee lossless summarization of arbitrary conversations.

Strict output-format checks still fail when this model adds Markdown fencing or changes exact wording/capitalization. Those failures remain in the artifact, separately from cosmetic-normalized factual scores. The logic case used 1,689 output tokens in every path; the initial 768-token run cut it off in all paths. The same answers with a sufficient budget do not indicate intelligence degradation in the optimized transport.

## Other changes in this batch

- Cleaner composer, model selection beside input, auto-growing text fields and consistent spacing. Studio receives its corresponding composer/menu/layout fixes separately.
- Training controls, dataset guidance, feasibility feedback and a chat LoRA-adapter selector; fixes rank versus number-of-layers wiring.
- Z-Image Turbo donor recognition with a 9-step/zero-guidance variant fallback, subordinate to model metadata and user overrides.
- App-session Keep Awake assertions, truthful active state, macOS parent-lifetime protection and Windows same-thread assertion ownership.
- Image-edit phase reporting, carriage-return progress parsing and a no-progress timeout with subprocess cleanup.

## Validation boundaries and remaining work

950 backend tests passed; one skipped. Uncloud's 119 frontend tests and Studio's 47 frontend tests passed. Both frontend builds passed; lint has existing warnings but no errors. Browser fixtures exercised 18 Uncloud surfaces, expanding/shrinking input, narrow layout, and the 75% Compact/inspect-memory flow. A real macOS wake assertion was observed and released. Windows wake behavior is unit-tested, not live-tested on Windows.

Image editing with real weights, voice latency/quality, full training runs, all model families, peak memory, cold-load performance and cross-platform runtime behavior remain unmeasured. Context limits are conservative estimates for complex/hybrid architectures. Model metadata/profile coverage needs ongoing expansion. The permission-history redesign and broader Chisel workspace UX are not completed by this batch.

## Next optimizations, ordered by available evidence

1. Preserve the measured scan/polling removal: about 202 ms saved here.
2. Avoid premature output limits: the logic fixture requires more than 768 generated tokens with this model. This is correctness, not a speed gain.
3. Use verified compaction to reduce large prompts; quantify prefill improvement on additional checkpoints before promising speedups.
4. Instrument native prefill/cache metrics, answer-first-token timing and peak memory; run fixed hardware/checkpoint comparisons across GGUF and other MLX families.
5. Evaluate quantized KV cache, speculative decoding, flash attention and voice streaming separately per backend. No new optimization flags are enabled without those measurements.
