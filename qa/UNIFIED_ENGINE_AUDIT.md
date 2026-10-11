# Unified inference and notification engine — v0.4.28

Verification date: 11 October 2026. This report covers Uncloud Chat and Chisel.
It distinguishes implementation from device verification. It does not claim
that every requested backend optimization or every model has been validated.

## A. Architecture findings — IMPLEMENTED AND TESTED

The direct path is: composer assembles the selected conversation and explicit
settings → authenticated local request → cached model profile and native
parameters → resident model server → immediate stream forwarding.
The model server owns native template rendering, tokenization, prefill and
generation. Ordinary Chat does not call a planning/orchestration model.

Chisel adds its tool contract and selected conversation context only on its
separate agent path. Permission checks live at execution, rather than merely
in the prompt. Durable interaction records are independent of a web socket.
Rust delivers native notifications independently of the webview.

The existing `/api/chat` compatibility endpoint still exists. The normal
frontend uses `/api/chat/runs` and its shared connection pool. The compatibility
endpoint is not included in the new warm transport benchmark.

## B. Existing functionality reused — IMPLEMENTED AND TESTED

Reused resident engine management; cached model/library profiles; hardware-aware
context discovery; llama.cpp `--parallel 1` and effective `/props` context;
MLX native templates; authenticated transport; event-driven streaming;
web-evidence native-token budgeting; scoped tool policies; runtime power
protection; task graphs; owner isolation; and existing developer diagnostics.
This release does not claim these established features as newly invented.

Reference semantics were checked against [Ollama context configuration](https://docs.ollama.com/context-length),
[LM Studio model loading](https://lmstudio.ai/docs/cli/local-models/load),
[llama.cpp server APIs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md),
and [Unsloth's template handling](https://github.com/unslothai/unsloth/blob/main/studio/backend/core/inference/chat_templates.py).
Unsloth is also a training framework, rather than an interchangeable desktop
inference provider.

## C. Inference capabilities — IMPLEMENTED AND TESTED

Chat and Chisel share strict settings validation and native payload assembly.
Controls include supported temperature, top-p/top-k/min-p, penalties, seed,
stop sequences, output budget and optional native format/grammar controls.
Unsupported fields, malformed values and unsupported reasoning levels are
rejected. Advanced fields are available only when the adapter declares support;
accepting a field name is not evidence that every backend supports it.

User overrides take priority. Native reset clears overrides authoritatively,
including previously saved defaults. Custom/empty Chat system prompts are
explicit; Chisel retains its mandatory tool contract. Presets support save,
replace, delete, versioned atomic import/export and model/conversation/project
scopes. Project defaults can be explicitly applied in the controls; headless
requests can select a project ID. This does not scan or attach project files.

## D. Reasoning controls — IMPLEMENTED AND TESTED

Auto preserves native behavior. A discovered `enable_thinking` template enables
Off/High as a native binary toggle, not a fabricated graduated budget. Explicit
template-declared `reasoning_effort` values enable only those declared levels.
Unsupported Low/Medium/Max entries remain disabled. Temperature and prompt
wording are not used to counterfeit reasoning effort.

Actual graded-budget hardware validation is **IMPLEMENTED BUT NOT VERIFIED**:
the installed test models do not establish every mechanism/level. Native
fixed-thinking models remain usable on Auto.

## E. Model-specific configuration — IMPLEMENTED AND TESTED

Capabilities are discovered once at load from model configuration and native
templates, plus installed adapter source/version where available. Cached
recommendations and their sources are inspectable alongside effective request
parameters. No per-turn metadata/file lookup was added to payload assembly.
Unrecognized models retain backend defaults instead of guessed family behavior.

Advanced loader tuning, universal speculative decoding and automatic backend
switching are **NOT IMPLEMENTED** by this release. Native llama.cpp capability
declarations are adapter-based; they are not exhaustive live flag probing.

## F. Context management — IMPLEMENTED AND TESTED

The bottom-right Chat counter counts the native formatted prompt against the
active runtime limit. Chisel counts its full planning contract and handoff.
At 75%, Compact becomes available. Explicit compaction consumes the selected
uncompressed prefix in native-budgeted stages and carries structured memory
forward. It does not simply delete older turns. Facts, decisions, constraints,
unresolved work and references remain inspectable; selected user prohibitions
and decision updates are retained verbatim. Failed replies are excluded.

Original Chat history remains stored and inspectable. Chisel can inspect its
original handoff during the current view session. After restart, durable graph
recovery preserves the goal, completed steps and outputs; full original Chisel
handoff persistence beyond the associated Chat is **NOT IMPLEMENTED**.

Native token-count failure, invalid/empty summaries, output truncation or no
size reduction preserve the original conversation. Already compressed raw
turns are not sent through repeated summarization.

## G. Performance results — IMPLEMENTED AND TESTED

Removed legacy effort-to-sampling interference in native Chat/Chisel payloads
and forced generic planner temperature/thinking overrides. Cached tokenizer
instances are reused for native context accounting. The model stays resident.
Optional completion notifications run after generation; they cannot prevent a
successful reply if the history store is unavailable.

Normal direct dispatch performs no library/project scan, retrieval, tool-schema
injection, file attachment processing or agent preparation unless selected or
implied by the enabled feature. The existing optional web path is distinct.
The context UI may initialize a tokenizer once after load; its cached counter
does not initialize the generation backend again.

No universal speed improvement is claimed. The balanced MiniCPM comparison
measured about 9.6 ms more median transport TTFT through Uncloud than direct
native transport. Existing backend prefix-cache reuse was observed, not newly
implemented. The benchmark excludes frontend/Rust/IPC dispatch and is not a
complete user Send-to-First-Token measurement.

## H. Chat integration — IMPLEMENTED AND TESTED

Shared model controls, native reset, saved defaults, explicit compaction,
native accounting, actual sampling inspection and completion/failure events
are connected. The developer direct-model mode continues to bypass project,
agent, tools, retrieval and normal system/context injection.

## I. Chisel integration — IMPLEMENTED AND TESTED

The same native profiles drive planning. Context overflow is checked before
execution. User questions are real scoped `ask_user` interactions with explicit
answers. Disconnected UI sessions no longer constitute lost approval state.
Completed work is retained on safe recovery; uncertain side effects are never
automatically replayed. A module/endpoint naming collision that broke resumed
execution and automation scoping was identified and fixed.

MiniCPM produced a valid native plan in one live run and an invalid plan in
another. The latter failed safely after two bounded repair attempts, with no
tools executed. Reliable planning for every small model is **NOT IMPLEMENTED**
or demonstrated; this is a remaining model/output reliability limitation.

## J. Tool permissions — IMPLEMENTED AND TESTED

Scoped ContextVars isolate concurrent permission/question askers. Each Chisel
run has a fresh Gate. Tool-group and device-access revocation are checked again
after a permission wait. An explicit empty tool-group selection means no tools.
Sandbox/workspace restrictions and integration permission gates remain active.
Permission controls are separate from inference and notification preferences.

## K. Notification engine — IMPLEMENTED AND TESTED

Centralized completion/failure, permission, question, background, download and
update events feed a persistent bell inbox. Read/dismiss/filter/clear and
category/global preferences work without relying on OS display. Private OS
previews contain generic text, not user prompts or secrets. Dedupe prevents
repeated/stale native submission. Pending requests survive notification dismissal.

Native APIs are implemented in Rust with `notify-rust` 4.18.2. macOS uses
UNUserNotificationCenter; Windows uses toast notification APIs; Linux uses
D-Bus desktop notifications. Display/click verification is discussed below.

## L. Sound — IMPLEMENTED BUT NOT VERIFIED

Optional system sounds and quiet mode are implemented. Windows requests the
  adapter's explicit Default sound when enabled; an omitted sound is silent in
  that adapter, which was corrected during source inspection. The dispatcher uses
normal OS priority, with no direct audio player, critical interruption flag,
Focus override or copyrighted custom sound. Audible OS behavior was not
verified. Custom audio-file selection is **NOT IMPLEMENTED**.

## M. Operating-system compatibility — IMPLEMENTED BUT NOT VERIFIED

macOS Rust compilation and native Settings/inbox UI checks passed. The initial hand-assembled temporary
QA bundle received `NotDetermined / NotSupported` and a native request rejection:
`Notifications are not allowed for this application`. Actual visible native
delivery and click navigation are **BLOCKED** on that test bundle; they must not
be described as passed. The UI now reports refusal and preserves inbox access. A correctly Tauri-packaged
  QA bundle subsequently opened the native permission prompt. Its system dialog
  requires manual user interaction because the UI-control tool cannot access it.
  Until allowed and visually checked, delivery/click tests remain unverified.

Windows/Linux native branches are implemented, but their physical-device
notification presentation, sound, click and Focus/Do Not Disturb tests have not
been run here. CI compilation/packaging is a separate verification boundary.
macOS Intel remains excluded because the current engine dependency set cannot
install there; this release does not change that existing limitation.

## N. Approval workflow — IMPLEMENTED AND TESTED

Accepting an answer requires the owning principal, a matching live waiter,
pending request, matching waiting run and unexpired TTL. Forged, foreign,
duplicate, cancelled or restarted requests cannot authorize execution.
Notification clicks only resolve an authenticated record and navigate.
Fresh explicit approval remains necessary. No OS action grants permission.

## O. Background lifecycle — IMPLEMENTED BUT NOT VERIFIED

Default close quits. Explicit Keep running in background changes close to hide;
the tray offers Open, Stop active tasks and Quit. Rust polling continues while
the webview is hidden. Full native close/hide/tray behavior is not yet verified
on all OS devices. Terminated applications do not pretend to send notifications.
Resuming after restart creates a new run and new approval scope. Automation
completion/failure notices are wired; resumable automation clarification prompts
are **NOT IMPLEMENTED**. Conservative background scope remains enforced.

## P. Persistence/privacy — IMPLEMENTED AND TESTED

History, inference defaults, interactions and saved graphs use an authenticated
AES-256-GCM encrypted store, atomic replacement and owner isolation. Local file
permissions are 0600. Corrupt/undecryptable originals are preserved, with an
explicit error and no silent plaintext fallback. Answers are not stored as
reusable authorization. Finished records are bounded; active requests are
protected from history clearing. Existing vault/key protections are reused.

## Q. Tests — IMPLEMENTED AND TESTED

- Backend: local workspace 1,050 passed, 1 skipped; the published-source Linux
  CI suite passed 1,026 with 12 optional-runtime tests skipped. Local totals
  include existing unpublished legal tests; those are excluded from this commit. Warnings include existing deprecated FastAPI
  lifecycle/TestClient APIs and TorchScript warnings.
- Frontend: 135 tests across 18 files passed. TypeScript/production build passed.
  Lint passed with existing warnings and two non-failing component warnings.
- Desktop: 5 Rust tests passed; formatting and locked compilation passed.
- Release metadata: six desktop version fields and 135 bundled runtime files
  verified for 0.4.28. Sidecar package version intentionally remains 0.3.0rc2.
- Live native UI: final version display, single Notifications panel and inbox
  fallback inspected in a disposable QA configuration.

## R. Benchmarks — IMPLEMENTED AND TESTED

Same installed model path/server, same prompts and temperature 0 / seed 42;
native and Uncloud modes alternate order for warm benchmark rounds. Small sample
sizes support diagnosis, not general device-wide performance claims.

| MLX model | Native warm TTFT median | Uncloud warm TTFT median | Strict task score: native / app |
|---|---:|---:|---:|
| MiniCPM5 2B, 8-bit | 103.51 ms | 113.10 ms | 5/6 / 5/6 |
| Llama 3.1 8B | 152.79 ms | 99.86 ms | 2/6 / 2/6 |
| Qwen3.5 9B, Q4 | 702.93 ms | 451.37 ms | 4/6 / 4/6 |

MiniCPM medians use four rounds per mode; Llama/Qwen use two. Llama/Qwen
answered all six cases identically between modes. Strict scores include JSON
instruction compliance: several Llama answers had correct facts with extra
prose and therefore failed. The logic puzzle failed in both paths for all
three tested models. These findings do not justify describing the models as
universally more intelligent after this change.

MiniCPM runtime cold readiness was 2,078 ms; first warmup inference was
3,738 ms. Warmup includes first-use model/kernel work and is excluded from the
median. Its warm generation rate estimated from native completion token usage
and post-first-token duration was about 45 tokens/s in both paths. Cache usage
reported 24 of 25 prompt tokens reused in repeated warm prompts.

Production context compaction reduced 2,191 native tokens to 314 (85.7%) and
retained 10/10 factual continuity checks. It retained the explicit prohibition
against deleting the original catalogue. Incremental compaction received only
prior memory plus two new turns, correctly moved release to Wednesday and
removed completed approval work from current open tasks.

Evidence: `unified-runtime-final.json`, `unified-runtime-results.json`,
`unified-llama-results.json`, `unified-qwen-results.json`. The earlier
`unified-runtime-before-memory.json` retains a failed structured-memory
experiment rather than hiding it. `verify_unified_runtime.py` is repeatable.
No v0.4.26-versus-v0.4.27 same-device speed gain is claimed: this release's
measurements compare native transport against the current app, and full against
compacted context. Peak memory, isolated tokenizer/prefill/kernel timings and
every backend's before/after results remain **NOT IMPLEMENTED** measurements.

## S. Security verification — IMPLEMENTED AND TESTED

Tests cover authenticated routes, owner separation, forged/stale answers,
restart invalidation, approval isolation, revocation during a wait, no replay of
ambiguous writes, atomic preset validation, encryption/tamper handling, bounded
records and notification failure independence. Notification sources cannot
introduce arbitrary executable URLs. This is application scope enforcement,
not a claim of kernel/container isolation for arbitrary device access.

## T. Files modified — IMPLEMENTED AND TESTED

New backend modules: `inference_controls.py`, `control_api.py`, `compaction.py`,
`user_events.py`, `job_events.py`, `agent/questions.py`.
Integration changes: `main.py`, `chat.py`, `context_count.py`, `engines.py`,
`agent/{approval,graph,orchestrator,tools}.py`, automation/downloader/media engines.
Frontend: shared inference hook/controls/tests, NotificationCenter,
NotificationsSettings, ChatView, ChiselView, SettingsView, GuideView, App,
UpdateBanner and sidecar/context clients.
Release-script Python 3.12 import classification is now explicit in `ruff.toml`.
Desktop: `notifications.rs`, `lib.rs`, Cargo dependencies/lock and synchronized
release versions. Tests: unified API, controls, recovery, planning and
permissions. QA benchmark/report files are included. Unrelated local legal
and design changes are excluded from this feature commit.

## U. Known limitations

- **BLOCKED:** actual native alert display/click on the rejected QA bundle.
- **IMPLEMENTED BUT NOT VERIFIED:** Windows/Linux hardware notifications and
  GGUF/CUDA native live inference; granular reasoning mechanisms; full native
  background/tray behavior; audible sounds.
- **NOT IMPLEMENTED:** cloud inference-provider execution; universal native
  thinking budgets; custom notification audio; automatic speculative decoding;
  all-backend memory/prefill instrumentation; interactive background automation
  clarification recovery; persistent original Chisel handoff independent of Chat.
- Planning and summarization still depend on the selected model's ability to
  produce valid structured output. The application fails safely when it cannot.

## V. Recommendations, in evidence order

1. Verify packaged native notifications/permission registration on macOS, then
   Windows/Linux display, click, mute and Focus scenarios before marking delivery
   production-verified. The persistent inbox is already the safe fallback.
2. Address the measured model instruction/planning failures using a broader
   same-file evaluation set and native constrained output where truly supported.
3. Extend native stage instrumentation and measure full UI-to-first-token latency
   before selecting optimizations or asserting further speed gains.
4. Expand actual-device GGUF/CUDA/Metal family coverage; keep unsupported controls
   disabled until backend mechanisms are established.
5. Add persistent Chisel handoff memory and automation clarification recovery
   with the same fresh-approval and no-replayed-side-effect guarantees.

Release status and installer links are verified separately after CI completes.
Download links in README use `/releases/latest/download/` and advance only when
GitHub publishes the new release and its signed updater manifest.

The initial v0.4.27 build was stopped by a release-script import-order lint
error after its Linux backend tests passed. v0.4.28 retains that tag unchanged
and retries with explicit Python 3.12 lint configuration and updated notes.
