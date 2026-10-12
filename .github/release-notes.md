Ordinary Chat now sends no built-in app identity or system message. Web/image instructions activate only for requested work; greetings bypass search. Explicit prompts, selected styles, native templates, model sampling recommendations and agent safeguards remain supported.

Fixed “Context unavailable” and reply-budget failures caused by saved output ceilings larger than the runtime window. Input counting no longer validates output settings. Auto output uses model metadata or the installed backend's declared default instead of inflating replies with context size. Native unbounded GGUF defaults remain unbounded.

Auto uses a supported native non-thinking template for plain greetings, visibly labelled “Auto · quick greeting”. Explicit effort, custom thinking limits, custom prompts and raw mode take priority. Search providers run concurrently with one bounded fallback. A supplied source URL can bypass search. Busy-agent conflicts no longer trigger model-start recovery.

Sequential Apple Silicon comparisons used the same Qwen, MiniCPM and Llama model files and native templates. Lean chat matched the native baseline's answer exactly on all three. Qwen's final Auto greeting completed in 0.89 seconds, first text at 308 ms. These are device-specific measurements, not universal speed or intelligence guarantees.

The tests also preserve failures: MiniCPM's non-thinking arithmetic mistake occurs in the native baseline too, native thinking can ramble, and the public search provider still returned unrelated results for the tested query. Windows/Linux and incomplete Gemma generation were not tested on this Mac.

The Guide was updated. Local checks passed 1,072 backend tests (10 skipped), frontend regressions, production build, backend lint and release-resource validation. Full measurements, original outputs, cache differences and limitations are in [the direct Chat audit](https://github.com/UnnamedCoder-568/Uncloud/blob/main/qa/direct-chat-audit-2026-10-12.md).
