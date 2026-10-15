# Native inference cleanup — v0.4.32, 2026-10-15

## Scope and evidence boundary

This release removes app-created inference policies and fixes a reproduced runtime mismatch. No model files or weights were changed. All native tests ran sequentially on one Apple Silicon Mac; each test owned one worker and stopped it in `finally`. Chrome was not opened or controlled. Raw results include failures, prompts, sampling, configuration SHA-256 and weight sizes/mtime. Weight contents were not rehashed. This is a small regression sample, not proof of broad intelligence or Windows/GGUF performance.

## Current path

- At model load: read cached model/config/template capabilities, choose the native runtime from actual components, establish the effective memory-aware context, load weights once and retain them.
- Typed direct chat: user input + valid conversation/inspectable compacted memory + explicit overrides → cached payload assembly → persistent HTTP connection → native template/tokenizer → prefill → native sampling → immediate stream.
- Ordinary typed chat adds no app identity, voice manner, greeting inference rule, tool schema, project scan, agent preparation, retrieval or orchestrator model. The context meter runs independently, not as a prerequisite for direct Send.
- Explicit/requested web, picture and voice features retain their scoped instructions. Relevant current-information requests can still retrieve with the user's Web switch enabled; retrieval is not claimed to be removed from such requests. Chisel retains its agent/tool contract.
- Native EOS, template and tokenizer remain authoritative. Manual ceilings are retained as preferences; physical context bounds may reduce an effective request ceiling without rewriting the saved value.

## Reproduced intelligence and latency problems

1. A saved voice manner leaked read-aloud formatting into typed chat. The screenshot's greeting prompted lengthy constraint checking. Typed chat now ignores voice formatting; spoken replies can still use the selected manner.
2. The app selected non-thinking mode for recognized greetings. Removed the classifier from inference and its UI badge. Auto sends no thinking flag.
3. App effort presets and fractional thinking budgets changed native inference. Removed synthetic Fast/Deep/Creative/Deterministic presets, automatic fraction allocations, and the custom MLX thinking sampler. User-created named presets and explicit native controls remain.
4. Qwen3.5 9B's downloaded checkpoint declares a vision encoder and processor, and its own model card specifies mlx-vlm. The catalog/import/runtime sent it through mlx-lm. Both app-like and direct native requests there failed to produce a final identity answer within the diagnostic. Runtime selection now follows components, including renamed checkpoints; no question/model-name rule participates.
5. mlx-vlm requires a `model` field even with weights selected on its CLI. The chat payload now includes it. The selected LoRA adapter is forwarded/preloaded too, avoiding a silent adapter loss on the corrected route.
6. Native mlx-vlm Auto uses its own declared default thinking mode. Cached recommended sampling now follows that native mode; Auto itself does not inject a toggle. Model generation metadata/local configuration and explicit user settings take priority over labelled, sourced architecture fallbacks.
7. Switching models replaced manually chosen limits/settings. Explicit Chat overrides now persist across switches until reset; native recommendations change only in Auto.
8. Decoder MLX's generic library 512-token output ceiling was not a model capability. Auto now uses the selected effective window, with a small context adapter bounding output using the native prompt's existing tokenization. No second tokenizer pass, sampler replacement or history truncation is added by that adapter.
9. Successful compaction was subsequently counted as a system-only request, which Qwen's native template rejects. The final memory check now includes a valid user turn.

## Before/after observations — same Qwen files

- Original reproduced app-style request: read-aloud system prompt, output ceiling 512 and automatic thinking budget 64; 1,776.8 ms to first token, 45,262 ms total, ended at length with analysis rather than a proper final identity answer.
- Removing rules while keeping the wrong mlx-lm route was insufficient: native identity, greeting and probability cases still hit the 60-second diagnostic without final answers. These failures remain in `native-chat-after-qwen-2026-10-15.json`.
- Correct native mlx-vlm route with Auto and source-recommended sampling: identity first token 431.9 ms, total 6,800 ms, correctly identifies Qwen3.5. A matching direct native request produced the identical answer (482.3 ms first token, 6,891 ms total).
- Actual app transport: same identity answer, 796.0 ms first token, 6,808 ms total; probability 440.6 ms first token, 9,795 ms total. Prompt assembly measured 0.016–0.025 ms, dispatch 0.149–0.179 ms. App identity was the first request after model start in this separate run; it is not a warm/cold-controlled comparison with the prior native run.
- This changes runtime and native thinking mode as well as app prompt policy. It demonstrates a functioning native route, not a quantified same-mode engine speedup or isolated causal gain for every individual deletion.

| Route | Case | First token, ms | Total, ms | Finish |
|---|---|---:|---:|---|
| Qwen native | auto_greeting | 358.9 | 3531.1 | stop |
| Qwen native | auto_probability | 421.9 | 10128.0 | stop |
| Qwen native | auto_code | 352.4 | 1648.9 | stop |
| Qwen native | context_recall | 445.5 | 4173.7 | stop |
| Llama native | auto_greeting | 356.0 | 4968.2 | stop |
| Llama native | auto_probability | 473.7 | 11860.2 | stop |
| Llama native | auto_code | 394.7 | 1473.4 | stop |
| Llama native | context_recall | 482.8 | 2374.9 | stop |
| MiniCPM native | auto_greeting | 198.1 | 7735.2 | stop |
| MiniCPM native | auto_code | 550.4 | 13497.0 | stop |
| MiniCPM native | context_recall | 249.7 | 6665.3 | stop |
| Qwen app transport | app_identity_native_defaults | 796.1 | 6807.9 | stop |
| Qwen app transport | app_probability_native_defaults | 440.7 | 9794.8 | stop |

## Quality, context and streaming checks

- Qwen Auto: native identity correct; exact probability 3/10 with valid explanation; correct Python square function; Cedar/$48/Tuesday/no-publishing recall correct.
- Llama: square and recall correct; probability calculation 3/10 correct, but it added an incorrect aside claiming a higher proportion of blue balls. Marked a native quality limitation, not a full intelligence pass.
- MiniCPM: Auto reply, square function and context recall complete/correct. Its deliberately capped 32-token cold warmup ends at length, as expected for that diagnostic ceiling.
- Actual app path: identity/probability checks passed. Cancelling after the first frame completed in 508.3 ms total; no model worker remained after test cleanup.
- Explicit native Qwen thinking On: first reasoning token 430.4 ms, no final answer by the 60-second diagnostic. This was already direct native HTTP using the app-built payload, with no system prompt or app thinking budget. The record remains a failure/limitation. On/off support is presented as On/off, not a fictional graded High slider. High thinking is not a guarantee of a fast or correct answer.
- Context compaction on the same Qwen file: 1,819 tokens → 691 tokens for memory plus recall request, 25.41 seconds to summarize/count. Original history is retained; inspectable JSON preserves Cedar, budget 48, Tuesday, no publishing, and completed review state. Recall after compaction preserves those four checked fields, but the summary omitted the original currency label ("dollars"). This is a lossy-memory limitation; the sample does not establish lossless continuity for arbitrary conversations. This uses structured summarization of selected new context, not blind token/history truncation.

## Recorded backend timings and remaining bottlenecks

The app probability request reported prefill 390.2 ms (120.4 prompt tokens/sec), generation 12.29 tokens/sec and peak MLX memory 6.879 GB; no reusable prefix tokens were reported. Identity reported prefill 506.3 ms, generation 12.47 tokens/sec and peak 6.731 GB. These are native runtime metrics, not process-wide peak RSS.

File I/O, tokenizer initialization, template rendering, IPC and GPU queue time are not individually separated in these traces. No invented numbers or zero-overhead claims are made for uninstrumented backend stages. App request construction uses cached metadata; source regression tests forbid model-library scans on Send. Backend-internal tokenization/context validation can still perform its own work.

Next work in evidence order:

1. Investigate the native thinking-On checkpoint behavior; reproduce and diagnose upstream, without adding greeting rules or forced app token fractions. No high-effort quality guarantee is claimed.
2. Measure compatible native prefix caching: current Qwen traces report zero cached tokens. Benchmark with identical prompts/sampling before enabling new cache settings.
3. Profile native prefill/generation kernels and tokenizer sub-stages. At measured app assembly under 0.03 ms, more Python routing abstractions are not the demonstrated bottleneck.
4. Run same-file Windows/GGUF/Gemma checks on their actual hardware. Cross-platform unit tests and installer CI do not establish device-specific inference speed or intelligence. No CUDA/Windows runtime performance gain is claimed here.

## Validation and release

- Exact selected release source: 1,086 backend tests passed, 3 skipped in the isolated source archive.
- Frontend: 148 tests passed; production TypeScript/Vite build passed; lint has existing warnings and no errors.
- Python lint and release-resource checks passed (139 runtime files).
- Five desktop shell tests passed. GitHub Linux source CI also passed: 1,064 backend tests, 12 optional dependency/platform skips, frontend checks and five desktop tests. Platform packaging is recorded in the release workflow.
- See all adjacent `native-chat-*-2026-10-15.json` files for preserved before, intermediate, final and failed observations.

The native inference changes do not require project, file, retrieval, agent or orchestration preparation for an ordinary direct chat turn. Optional features remain available on demand.
