# Direct Chat audit — 2026-10-12

Raw run records and screenshots are retained privately rather than published
with the source. References to capture filenames below identify those private
records; the reported measurements and failure summaries are unchanged.

## What changed

Ordinary Chat sends the conversation and user input through the model's embedded native template. It adds no application name, mode descriptions, date, lookup syntax, image-generation instructions or default system message. Explicit custom prompts, selected writing styles, retained compacted memory and requested attachments remain authoritative.

Web and image capability switches are permissions, rather than instructions injected into every turn. Outside-information requests receive short source instructions and measured evidence. Greetings and questions about the existing conversation do not search. An explicitly supplied page URL is read directly. Chisel still receives its tool contract, permissions and sandbox controls; direct Chat does not invoke an orchestrator.

## Actual path

1. Send assembles the existing conversation, explicitly retained context and user attachments, if any. It resolves cached request preferences.
2. A plain greeting in Auto can select the model's discovered native non-thinking template. The composer shows **Auto · quick greeting**. Explicit effort, thinking limits, custom prompts and raw mode override this choice. No classifier model, rewritten user prompt or second inference pass is involved.
3. The frontend submits `/api/chat/runs` immediately. It does not wait for the context meter or perform a model-status preflight. Recovery starts a model only for the explicit unloaded/switched-model error; an agent-busy conflict no longer causes a start/retry.
4. The backend validates ownership and resident-model identity, resolves cached sampling/template controls, and sends the native request through its persistent local HTTP client.
5. The resident backend renders its embedded template, tokenizes, prefills and streams. Frames remain available for reconnects. History saving and completion notifications occur after generation.

The optional context meter runs separately, after a 550 ms input debounce. Web evidence fitting waits for native counting only on turns that actually require external evidence. There is no project scan, automatic file retrieval, memory search, tool-schema injection or orchestrator model on a plain turn.

## Verified unnecessary work and failures

| Finding | Fix |
|---|---|
| App identity, Chisel description and generic web protocol in every chat prompt | Empty built-in direct-chat prompt; capability instructions scoped to requested work |
| “How are we today?” routed to web search, including after an unrelated failed product lookup | Recognize complete social greetings; keep mixed research requests distinct |
| Enabling Pictures injected image syntax into unrelated turns | Add it only for an explicit image request |
| Input counting validated reply ceilings and could return “Context unavailable” | Count only native template-affecting controls; output settings cannot disable input counting |
| Saved 4,096-token reply ceiling blocked a 1,024-token runtime window | Preserve the saved ceiling; bound the effective request; show the runtime bound |
| Web evidence reserved an impossible oversized saved reply allowance | Fit evidence against native input counts and a practical reserve, retaining URLs and conversation continuity |
| MLX Auto output inflated to one quarter of context — 14,336 tokens on the tested Qwen window | Read the installed backend's declared default once at model load; use model metadata first |
| Unbounded GGUF Auto implicitly acquired a made-up output ceiling and reasoning allowance | Preserve native stop behavior when no model/runtime ceiling is declared |
| Native default-Off templates acquired unnecessary limiter fields | Preserve default-Off behavior without an invented thinking budget |
| Every 409 conflict triggered model-start recovery | Recover only the unloaded-model conflict |
| Frontend-resolved requests still acquired the saved-settings lock | Read inherited defaults only when requested |
| Five serial search attempts could block a turn | Race the two existing providers, cancel the losing request, then allow one topic-only fallback |

The original and failed native experiments remain in the accompanying JSON reports. They were not replaced with another model to conceal a failure.

## Controlled native measurements

Apple Silicon, macOS 27.0.1, installed MLX-LM 0.31.3. Exact same local files, embedded templates, fixed seed 42 and matched sampling/output controls within each comparison. Only one model worker was resident at a time. Each worker unloaded in `finally`; a process guard refused competing inference workers. Chrome was not operated.

The native baseline uses the same resident server and transport with the app's reasoning limiter removed. This establishes answer/template parity, **not** an end-to-end frontend-versus-CLI overhead benchmark. Fixed non-thinking comparison settings were temperature 0, top-p 1, top-k 0, presence penalty 0 and repetition penalty 1. Automatic/High cases use discovered model profiles and the installed output default.

| Model | Before → after input tokens, probability question | Warm old-prompt TTFT | Warm lean-repeat TTFT | Native baseline TTFT | Auto greeting first text / complete reply |
|---|---:|---:|---:|---:|---:|
| Qwen3.5 9B Q4 | 151 → 47 | 444.2 ms | 341.9 ms | 349.7 ms | 308.0 / 891.2 ms |
| MiniCPM5 2B 8-bit | 149 → 48 | 93.1 ms | 67.4 ms | 75.6 ms | 145.2 / 357.6 ms |
| Llama 3.1 8B | 164 → 70 | 103.6 ms | 119.4 ms | 120.7 ms | 243.1 / 1,381.7 ms |

Use the JSON values as authoritative if rounding differs. MiniCPM and Llama reused nearly the whole repeated prompt: respectively 47/48 and 69/70 input tokens. The old repeated prompts also reused their prefixes. Their first uncached lean requests took 154.3 and 294.5 ms; do not compare those directly against a fully cached old prompt. Qwen reported zero cached tokens on these requests. Removing prompt overhead reduced its warm TTFT by about 102 ms in this sample. This is not a universal speedup claim.

Across these direct comparison records, payload assembly was approximately 0.01–0.06 ms and dispatch approximately 0.08–0.24 ms. Cold first requests were much slower because of backend weight loading and warmup; the first Qwen answer began at 6.21 seconds. Normal warm turns kept their resident model and required no metadata/tokenizer initialization or file scan in the payload builder.

All three models produced **identical lean and native-baseline answers** under matched non-thinking controls. This includes MiniCPM's arithmetic mistake; native parity is not proof that the model's answer is correct.

## Quality and thinking

- Qwen's old app prompt stated the wrong probability (3/5), then calculated the correct result (3/10). The lean/native answers consistently gave 3/10 in this fixed check.
- MiniCPM's old prompt calculated 3/10 but appended an unnecessary search command. Lean and native non-thinking answers both incorrectly simplified 6/20 to 1/2. High effort returned the correct 3/10. This intrinsic non-thinking quality failure remains recorded.
- Llama answered the probability question correctly through both paths. It does not advertise a High-effort toggle, so that unsupported control was not simulated.
- Coding, exact project/deadline/budget recall and supplied-source citation checks completed on all three models. These are small regression checks, not a broad intelligence certification.
- Qwen's native Auto greeting used all 512 output tokens thinking and returned no answer. An early bounded Auto test with an added one-sentence constraint also rambled after the forced thinking boundary. These failures led to the disclosed native quick-greeting policy; its final greeting completed without reasoning in 0.89 seconds.
- Qwen High effort completed the probability answer in 15.10 seconds, first answer text at 10.15 seconds. MiniCPM High completed in 6.29 seconds. Higher effort intentionally spends longer thinking; it cannot guarantee that every model will reason well or finish every task.

Probability grading checks the stated conclusion rather than simply finding “3/10” anywhere. It rejects a contradictory stated answer but permits intermediate fractions such as 3/5 and 2/4. Regrading did not alter model inputs or recorded output.

## Search measurements and limitation

The same public iPhone query failed relevance checks before and after: **2.429 seconds → 1.258 seconds**. That is a reduction in failed-query waiting, not a successful search or verified product answer. Irrelevant provider pages are still rejected rather than handed to the model as facts.

Provider requests have an 8-second concurrent deadline and one 6-second topic fallback; destination reading retains its 12-second bound. The stalled-request path is now bounded around 26 seconds rather than five 15-second serial searches plus reading. Network scheduling can add a small amount of overhead. A supplied official URL bypasses search. Reliable provider APIs remain a separate improvement requiring configured credentials.

## Validation and remaining boundaries

Search follow-up for v0.4.31: inspecting the actual provider responses found that DuckDuckGo had returned relevant results, but the reader assumed `class` came before `href`. Bing's query also retained conversational “So” and returned dictionary entries. Both failures reproduced in added tests. The reader now tolerates attribute order and extra classes, and the normalized query drops “So”. The same live query succeeded, including four destination reads, in 2.068 seconds. See `public-search-2026-10-12.json`. The earlier failure measurements above remain unchanged. This corrects the confirmed parsing/query bugs, not every possible public-provider availability failure.

- Local CPU regression suite: **1,072 passed, 10 skipped**; skips concern unavailable platform/optional dependencies. Backend lint passed.
- Frontend regression suite and production build passed. Existing frontend lint warnings and large-bundle warnings remain outside this inference fix.
- Native examples cover Qwen, MiniCPM and Llama MLX files. Model metadata and native chat templates were preserved. Context/oversized saved-ceiling and source-fitting regression tests passed; existing structured compaction and retained-context tests remain included.
- Windows/Linux native generation and Gemma generation were not run on this Mac. The Gemma download is incomplete and was preserved. The Windows packaged llama.cpp path is currently CPU-only; this release does not introduce a GPU backend or claim Windows performance measurements.
- Peak unified-memory usage, a broad intelligence evaluation, end-to-end GUI TTFT and a newly run live compaction-quality benchmark are not established by this check. The installed app's visual update will come from the published installer.
- Native reasoning can continue writing analysis after a forced delimiter. Explicit effort preserves the model's behavior; this release avoids the problem for simple Auto greetings, removes excessive automatic output inflation, and records the remaining model-specific limitations.

Next priorities supported by this evidence: investigate Qwen's absent reported prefix-cache reuse; evaluate model-specific reasoning limits against more quality tasks; configure a reliable search provider; measure and implement suitable Windows GPU acceleration on actual target hardware. No measured cross-platform ranking is claimed.
