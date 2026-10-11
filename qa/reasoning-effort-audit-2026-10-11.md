# Thinking effort investigation — 2026-10-11

Scope: inspect the installed Uncloud app, its MLX runtime, the selected Qwen3.5 9B MLX Q4 model, production source, and previously saved diagnostic results. Tests remained stopped until the user explicitly authorized them again. The following validation was then performed serially with one resident model at a time; Chrome was not used.

## Confirmed control mismatch

The model's `chat_template.jinja` declares `enable_thinking`, but no `reasoning_effort` variable or graded reasoning levels. Its assistant prefix opens `<think>` by default and closes an empty thinking block only when `enable_thinking` is false.

`inference_controls.discover()` exposes Auto, Off and an internally named `high` value for this binary toggle. `apply()` translates `high` to `chat_template_kwargs: {enable_thinking: true}`. It does not allocate a separate reasoning budget. Auto leaves the native template unchanged, which also enables thinking for this model. High therefore does not buy additional verified control over reasoning or ensure a final answer.

The installed app's Model controls showed Auto, no overrides, empty sampling recommendations, MLX 0.31.3, 57,344 effective context tokens, and `max_tokens: 14336`. The visible stopped reply contained 1,551 words of thinking and no answer.

## Why generation can appear stuck

1. MLX 0.31.3 consumes a single `max_tokens` / `max_completion_tokens` output ceiling. Its native generation switches from the reasoning channel to the answer channel when the model emits the thinking-end tokens. The installed server does not consume a separate reasoning-token budget or graded effort field.
2. All reasoning tokens consume that same output ceiling. A reply can finish with `length` before it produces an answer, or spend a long time reasoning within a large ceiling. A larger ceiling allows more thinking; it does not compel the transition to an answer.
3. `streamChat()` refreshes its two-minute inactivity timer for every arriving frame. Repetitive but continuing reasoning is activity, so the timer cannot detect this as a semantic failure to answer. It is an inactivity guard, not a reasoning budget or repetition detector.
4. The installed web prompt tells the model to emit a search marker, then STOP and wait for results. Lookup execution occurs only after a completed final response, not from private reasoning. Previously saved reasoning repeatedly revisits that instruction. This is a separate protocol problem; pending source changes prefetch ordinary specification queries and remove lookup instructions after evidence arrives.
5. This model has no generation_config.json or local inference override file. The installed app consequently sends no sampling recommendations, leaving MLX's default temperature 0, top_p 1 and top_k 0. These differ from the publisher's thinking-mode recommendations. This is a verified configuration mismatch, not proof that sampling alone caused or can cure the loop.

## Prior evidence and limits

- Original web handoff: 84.18 seconds, 2,048-token diagnostic ceiling, 1,207 thinking words, `length`, no final answer.
- A previous native-thinking web fixture with publisher sampling still exhausted its 2,048-token ceiling without an answer. Prompt simplification and sampling changes alone have not demonstrated a reliable cure.
- A later real-query diagnostic with the simplified prompt and full-history presence penalty reached its 240-second diagnostic deadline with 1,888 thinking words and no answer.
- A synthetic fixture with full-history presence penalty eventually answered after 212.31 seconds. Full-history presence penalty is not enabled as a production optimization: there is no evidence of a reliable or useful improvement.
- A previous explicit Thinking Off fixture produced an answer. This establishes a working non-thinking path for that fixture; it does not establish a fix for thinking mode.

Diagnostic ceilings and fixtures differed. Some runs overlapped other work and a second loaded model, so these records do not support a comparative speed claim or a universal intelligence conclusion. No equivalent Windows/GGUF failure was reproduced in this investigation.

## Initial presentation corrections

- The shared Chat/Chisel control labels binary templates as Thinking, with Auto, Off and On. True native graded templates retain Thinking effort and their supported levels.
- The binary-template preset previously labelled Deep is displayed as Thinking on. The stored `high` value remains compatible; it still means the existing native on switch.
- Unsupported thinking choices are not advertised as available levels.
- The control and Guide explain the shared reply budget and the lack of a separate thinking limit in this control.

These initial changes corrected capability presentation. The following runtime implementation supersedes the binary-only presentation on runtimes where the new budget control is available.

## Runtime implementation after the user requested the fix continue

- Added an app-owned MLX server extension. It delegates model loading, native templates, prefix caching, sequential/batched generation, cancellation and streaming to MLX. A request-local sampler emits the tokenizer's actual thinking-end sequence at the selected limit; generation then continues with the answer in the same request. A naturally completed thinking block is preserved.
- Sampler state remains on the device. The limiter does not copy token history to the CPU, scan history, synchronize per token, start another model, retry generation, or inject a second assistant prompt.
- The extension consumes `thinking_budget_tokens` from the request and passes its request-local configuration through native generation arguments. It respects the prompt's initial reasoning state and detects generated thinking-start tokens. Reopened blocks use the remaining allowance rather than resetting the budget. Thinking Off keeps the native sampler untouched. Unsupported draft-model/tokenizer combinations fail explicitly rather than pretending a limit was enforced.
- Added a shared request-budget policy used by Chat, Chisel, and other callers of `model_payload`. Automatic/Low allow up to one eighth of the effective reply allowance; Medium one quarter; High one half; Maximum up to three quarters. These are visible Uncloud policies, not publisher recommendations or fabricated native effort grades. Counts scale with the model/runtime reply allowance. Automatic levels reserve answer space and the closing delimiter; explicit token limits still must leave room for both.
- A saved local model `reasoning_budget` and explicit user overrides take priority over the automatic policy. Off disables the reasoning allowance. The effective request and controls show the selected thinking limit.
- Compatible native llama.cpp runtimes use their actual per-request `thinking_budget_tokens` API. Discovery requires the installed binary to expose the reasoning-budget CLI capability and contain the per-request field. The boundary is tokenized once by that resident backend during startup to reserve its actual delimiter length. If native metadata cannot be confirmed, the budget control is withdrawn; older/unknown backends do not advertise budget support. No fixed global budget is passed on the command line.
- Thinking effort is exposed on supported bounded runtimes. Binary-only runtimes continue to show Auto / Off / On. True native graded templates retain their declared effort controls alongside a verified budget when available.

Regression specifications cover effort scaling, answer reserve, explicit overrides, native request consumption, forced/natural endings, multi-token delimiters, independent requests, unsupported controls and unchanged Off behavior. They passed after the user reauthorized tests. Invalid native requests are rejected during tokenization, inside MLX's per-request error guard, rather than killing its batching worker.

Static verification: TypeScript compilation completed, Python syntax parsing and Ruff checks passed, the new runtime modules are included by the desktop packaging declarations, and the patch has no whitespace errors. These checks did not import model runtimes or run inference/test suites.

## Device validation after testing was reauthorized

Apple Silicon, MLX 0.31.3, the same local Qwen3.5 9B Q4 file and its embedded native template. Configuration SHA256: `a96942cb6a8a1d3f1d17514d81a1925d04362a6a3233b389d13012211baaa9f8`. Each process unloaded in `finally`; a process guard refused another resident inference engine and stopped the test if one appeared. Model requests were sequential. No browser/Chrome action was used for inference.

| Case | Thinking allowance | First streamed token | First answer | Total | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Synthetic evidence, Auto, seed 42, 1,024 output tokens | 128 | 6.43 s | 11.43 s | 19.02 s | Finished; fixture facts and source URL retained |
| Same synthetic evidence, High, unseeded | 512 | 0.76 s | 21.32 s | 37.59 s | Finished; fixture facts and source URL retained |
| Same synthetic evidence, Off, seed 42 | 0 | 0.24 s | 0.24 s | 7.07 s | Finished; 200 prompt tokens reused |
| Revised fallback search handoff, High, seed 42, 2,048 output tokens | 1,024 | 6.12 s | 46.31 s | 46.87 s | Finished with a search marker in the final response |
| Real-source evidence, direct native control, unseeded, 2,048 output tokens | Unbounded | 5.00 s | None | 100.77 s | Failed: all output spent thinking; length stop |
| Identical real-source evidence, High, unseeded | 1,024 | 0.22 s | 60.72 s | 115.30 s | Finished with an answer and supporting URL; 3,226 prefix tokens reused |
| Unverified specifications fixture, High | 512 | 0.36 s | 20.46 s | 24.77 s | Finished; specifications remained explicitly unverified |
| Normal Chat prompt, Maximum, probability question, seed 42 | 1,535 | 2.22 s | 62.27 s | 65.56 s | Finished with the correct exact fraction 3/10 in one sentence |

The uncapped/bounded evidence comparison used the same model, prompt, native template, sampling parameters, hardware and output allowance. It was unseeded, and the later bounded request benefited from prefix reuse. It proves a completed answer in this check, not a general speed improvement or an isolated cache-performance comparison. The bounded answer took longer overall because it actually produced an answer. Small synthetic fixtures used different allowances and are not comparable speed claims. Cold/warm readiness differs across rows.

Cancellation after the first reasoning token completed and the next request reached generation. Two raw-model Maximum-effort checks without the normal Chat system prompt, at 512 and 2,048 total output tokens, still rambled in the answer channel and ended at their output ceiling. The exact probability was present, but instruction-following/completion failed. This is retained as a limitation, not counted as a passing intelligence test. The normal Chat test used the exact same probability question and passed; no model or question was substituted.

An earlier fallback-handoff fixture failed despite a forced reasoning boundary. Its contract was revised to request only a final-response lookup marker and let the app fetch evidence before the next reply. Retesting the revised contract passed. Private reasoning never executes tools. Completed queries are deduplicated, lookup rounds are bounded, and the evidence phase removes the lookup protocol from the prompt.

Measured prompt construction in these requests was 0.008–0.045 ms and dispatch overhead 0.10–0.31 ms. Most remaining delay is model startup/prefill and generation. High/Maximum deliberately spend more generation time thinking; they cannot promise immediate correct answers. Peak unified GPU memory was not instrumented, so no peak-memory improvement is claimed.

## Slider and backend support

- The shared Chat/Chisel component now exposes a native range slider with discovered levels. A production-built isolated preview verified keyboard High → Max, its selected value, and clearing an explicit token override. Native ranges preserve keyboard focus. The screenshot is `qa/effort-slider-2026-10-11.jpg`.
- Compatible MLX LM uses the verified request-local limiter; Off retains native behavior.
- Compatible native llama.cpp uses its own per-request budget field. Detection requires actual binary support; unsupported versions retain only verified controls.
- Compatible MLX VLM uses its native `thinking_budget`, declared special-token boundaries and explicit template toggle. Gemma's default-Off behavior is preserved. Native `/v1/responses/input_tokens` now supplies the rendered prompt/image count. Capability discovery, payloads and counting are covered by regression tests, but on-device Gemma VLM generation was not tested because its download is incomplete.
- Older or unsupported runtimes do not receive invented thinking-budget fields. Explicit sampling and token limits remain authoritative. A bounded transition reserves answer space; it cannot guarantee answer quality for every quantization, prompt or raw-model request.

## Download correction

The previous progress state covered one file at a time. For the pictured Gemma repository, each large shard could reach 100% and the next shard reset the bar. The full pinned repository is 11,020,140,534 bytes across three weight shards and support files, rather than one 5.3 GB transfer. Its paused partial files were preserved.

Downloads now plan a pinned manifest, display cumulative verified bytes across all files, show the active filename, resume the same revision, retain completed shards, validate file sizes/ranges and claim completion only after all required files finish. Short responses remain resumable fragments. An active/completed download cannot accidentally restart from another click. Incomplete folders and legacy `.part` files are excluded from runnable library entries.

Regression tests cover cumulative progress, completion idempotence, persisted manifests, pause/restart, resumable ranges, ignored ranges, retained shards, short responses and incomplete library entries. A real pinned Hugging Face check downloaded only `config.json` and `chat_template.jinja`: both sizes matched the manifest, totaling 57,348 bytes. No model weights or duplicate runtime were downloaded for this check.

## Verification and limits

- 1,086 backend tests passed, one skipped.
- 146 frontend tests passed, including accessible bounded/binary/unsupported slider rendering.
- Production frontend build, lint, Ruff, release-resource verification and whitespace checks passed. Existing frontend warnings remain; they are not claimed fixed here.
- Guide explains the slider, override behavior, whole-model transfer progress and completion/resume behavior.
- Chrome remained untouched. Device checks used one Qwen model at a time; UI checks used the Codex in-app browser without loading a model.
- Native Windows/GGUF and Linux generation, Gemma VLM generation, a broad reasoning benchmark, peak memory and universal output-quality guarantees remain outside this device check. CI validates source and packaged engines separately.

Publisher reference: [Qwen3.5-9B model card and best practices](https://huggingface.co/Qwen/Qwen3.5-9B#best-practices).
