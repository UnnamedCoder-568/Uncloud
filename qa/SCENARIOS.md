# Uncloud end-to-end and stress matrix

Every row requires an observable outcome; a spinner alone is not success. Automated unit/integration coverage is distinguished from real engine and UI evidence. Use disposable configuration, workspace, outputs and credentials. Do not delete installed user models or contact third parties during tests.

| Module | Scenarios and required outcomes | Evidence / remaining boundary |
|---|---|---|
| Startup/install | Fresh start, missing runtime, retry failed install, complete readiness; correct version; optional engines stay optional | readiness, packaging, lifecycle tests; UI startup smoke; clean native installs require target devices |
| Navigation/UI | Open every module; collapse keeps navigation; history closed by default; open/close outside/Escape; menus; long multiline text; keyboard focus; resize | UI smoke and appearance/context tests; responsive visual inspection |
| Models | Scan/import metadata, missing/corrupt files, category filtering; download pause/resume/cancel; hide library entry; explicit file deletion approval; never delete unrelated files | models/import/removal/download integration tests; actual interrupted multi-GB download not yet exercised |
| Chat | Native templates; stream text/reasoning; model readiness/reuse; Stop/stall/error/retry; files/vision boundaries; model sampling and overrides | chat/profile/native/fast-path tests; same-model live baseline separately recorded |
| Context | Actual effective model limit; count template tokens; 75% threshold; structured compact memory; recent turns retained; inspect summary; repeat compaction without losing prior memory | context count/profile and frontend context tests; real-model continuity requires live evaluation |
| Web | Query extraction; relevance; fallback; fetch source content; network failure explained; no invented verification | web search and lookup tests; live providers require connectivity and can rate-limit |
| Friday/Talk | Listen → transcribe → model → sentence queue → audio → listen; duplicate events; cancel pending inference; late synthesis; failed mic retry; rapid stop/start; no stale output | lifecycle regression tests with fake device boundaries; real mic/speaker needs user device check |
| Voice | Engine selection; text synthesis; narration; transcription; voice conversion; missing weights; cancel; clip save/reopen/export | speech/narration/recast tests and UI tabs; listening quality and cloned identity require user judgement |
| Image | Model metadata defaults; distilled steps/guidance; user override/reset; LoRA compatibility; batch seeds/order; cancellation including queued jobs; edit/reference and output | image defaults/batch/stop/GGUF/runtime tests and UI; actual diffusion quality requires live generation |
| Product/Characters | Reference preserved; unsupported model blocked; character data saved/reopened; editing versus generation capabilities | placement/image tests and UI controls; identity/product fidelity requires visual review |
| Video | Family-specific defaults; native sizes/frame counts; duration/memory guard; unsupported model; cancel; save output | video families/defaults/budget tests; full native render depends on installed engine/model |
| Music | Instrumental/vocal options; durations/seeds; jobs/errors/cancel; stem/export paths and formats | music-related engine/stop/packaging coverage and UI; musical quality requires listening |
| Training/text | Valid and invalid JSONL; dry-run estimates; presets/advanced parameters; incompatible model; train/cancel; adapter discovery/export | training and quantize tests; real training convergence not proven by mocked runner |
| Training/image | Dataset/captions/path validation; supported architecture/runtime; LoRA job lifecycle; provider dataset generation safeguards | image training/provider tests; actual optimizer/adapter quality requires compatible installed trainer |
| Quantize | Supported source/format; output different from source; precision flags; adapter merge; cancel; disk/memory failure | quantize tests and UI; actual quantized output quality requires model comparison |
| Chisel | Plan/execute; tool discovery; scope/read/write/shell/desktop/network approvals; denial/retry; task state; preview refresh; stop | agent/core/permissions/computer/preview tests; native desktop permissions checked on target device |
| Automations | Create/list/run; one runner; schedule; pause/resume; missed runs; restart recovery; bounded history; no unattended write/device privileges | automations API/service tests; long sleep/wake timing requires soak on user device |
| Recipes | Validate steps/inputs; discover capabilities; run with current approvals; failed step reported; no partial false success | recipes/workflows tests and UI editor |
| Skills/MCP/providers | Discover skill; unsafe paths; classify remote tools; credential secrecy; invalid config; OAuth state; disconnected errors | skills/MCP/providers/auth/integrations tests; real account authorization needs user |
| Outputs | List/filter; confined downloads; export copy; reveal; deletion boundaries; missing output | output/API integration checks and UI; native chooser/reveal on target OS |
| Settings/security | All tabs; version; preference persistence; audit records and clearing; keep awake acquire/release; LAN auth/CORS | power/auth/LAN/permissions/desktop tests; physical sleep and permissions need device checks |
| Guide/legal | Current feature descriptions; no unsupported promises; terms rendering; accept version and notice distinctions | guide UI + legal tests; legal drafting not a substitute for counsel |
| Updates/releases | Offline/reconnect/focus; notices fail independently; signatures; channel/version comparison; installers + latest.json | desktop update tests and CI native builds; actual in-place upgrade on installed app needs user |

## Stress dimensions
1. Repeated open/close and stop/start, including pending async work.
2. 100 encrypted conversation save/load operations, independent identities, corrupted record handling.
3. Concurrent API reads and denied mutations; no auth bypass or leaked file contents.
4. Generation queues: cancel one versus all; no cancelled job starts.
5. Failed network, missing/corrupt files, malformed datasets, absent backend and invalid configuration.
6. Cold/warm model readiness and reasoning/instruction/context/coding on identical input.
7. Long context, compacted memory continuity and token limits; no silent truncation claims.

## Tests needing the owner
- Microphone/speaker on the actual installed app: Friday responds, Stop stops, retry works, no echo loop.
- OS permission prompts and real desktop control in a disposable workspace; deny then grant explicitly.
- Sleep/wake: screen may turn off, system stays awake while protection is enabled; disabling restores sleep.
- Windows/Linux clean installation and signed in-place upgrade on devices not available here.
- Real provider/OAuth/email accounts and paid APIs; no credentials or spending inferred from this test request.
- Subjective voice/music quality and reference-image fidelity; approve any use of a real person's voice.

Missing models/runtimes are local environment gaps, not automatically owner tasks. Do not download large models or call paid services merely to mark a row passed. Report those rows as not executed.
