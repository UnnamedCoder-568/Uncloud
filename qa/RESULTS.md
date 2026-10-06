# Uncloud bounded stress pass — 6 October 2026

## Automated result

- Backend: **1,008 passed, 1 skipped**. Isolated temporary configuration; local socket tests enabled. The skip is preserved rather than counted as passed.
- Frontend: **126 passed** in 16 files.
- Desktop Rust: **4 passed**.
- Production frontend compilation and release/runtime manifest verification: passed.
- Additional stress checks: 100 encrypted conversation round trips; 20 cancelled five-job image batches (100 jobs, zero started); 50 concurrent authenticated module reads; 20 unauthenticated engine-stop requests rejected.
- Five voice lifecycle regressions: duplicate turn prevention/cancellation, late synthesis after Stop, retry after microphone denial, Stop during native-listener startup, immediate audio completion.

Run again with `python3 scripts/stress_check.py --output /private/tmp/uncloud-stress-results.json`. This intentionally uses temporary settings and does not download models or invoke paid APIs. Required loopback socket/hardware queries must be allowed by the execution environment.

## Reproduced failures and fixes

1. Synthesized speech could play after Stop. Sessions now invalidate queued and late synthesized audio and release its blob URL.
2. Microphone startup failure left the running flag set, blocking retry. Failed startup cleans up and reports the error.
3. Audio completion callbacks were registered after play, leaving very short clips at risk of a permanent wait. Register first; surface playback errors.
4. Browser listening could resume before the queued spoken answer finished. The turn now drains the speech queue before resuming.
5. Stop during native listener startup could leave a listener behind. Late startup is released and stale events ignored.
6. Hidden screens stay mounted, so navigation did not guarantee microphone shutdown. Pane visibility now propagates through nested panes and voice sessions stop when hidden.
7. Guide lacked current workflows and contained unsupported memory/quality/speed claims. Rewritten with 14 topics and navigation links.
8. Quantize displayed one Mac's fixed throughput/RAM recommendation to everyone. Replaced with model/backend-dependent guidance; encryption history text now says device rather than Mac.

## Visible UI checks

Read-only isolated preview of the real production build: startup Continue; Chat, Friday, Models, Chisel, Automations, Recipes, Image, Video, Music, Voice, Outputs, Guide and Settings all opened without a screen error. Text Train, Image LoRA and Quantize controls rendered. Guide topic links worked. Chat history opened and Escape closed it; six-line input expanded to 138 pixels with no overflow in that test.

This preview prevents model jobs and writes and does not exercise native dialogs, OS permissions or actual media generation. These checks are smoke coverage, not proof of complete real-generation workflows.

## Installed-model check

MiniCPM5 2B MLX 8-bit, offline, isolated backend. Readiness: 1.56 seconds. Four fixed prompts (probability, exact JSON, supplied-context recall, basic Python function), three paths per prompt, identical sampling/model within each comparison. All 12 basic output checks passed.

| Path | Median first-token latency |
|---|---:|
| Direct backend | 96.8 ms |
| Current optimized transport | 104.7 ms |
| Reconstructed legacy transport | 298.8 ms |

Raw fixed-prompt evidence is in `live-chat-results.json`. This is a diagnostic comparison, not a new performance claim caused by this release. It excludes browser rendering and the sidecar inbound HTTP hop. Four basic checks do not establish general intelligence, long-context compaction quality, all families or all hardware.

## Not executed / limits

- Full diffusion/video/music generation, reference editing fidelity, real text/image adapter training and quantized output quality: integration/default/job tests passed, but real optimizer/render quality was not exercised in this pass.
- Real-model long-context compaction quality: deterministic context/profile/retention checks passed; the live prompt only checked provided-context recall.
- GGUF/CUDA/Windows/Linux inference on native target hardware: not available in this local MLX run; native installers are validated by release CI.
- Paid providers/account authorization, real microphone/audio, desktop permissions, physical sleep/wake and in-place update behavior require owner/device checks in SCENARIOS.md. They do not block source fixes or release.
- Existing lint warnings about hook dependencies/state effects and a large frontend chunk remain; lint has no errors. They are not represented as completed optimizations.
- Legal source drafts already present in the working tree were not changed or included in this release. Release CI also tests committed source.

No user models/conversations were deleted. No external messages were sent, no paid API calls were made, and the isolated live text backend was stopped after benchmarking.

## Release validation follow-up

v0.4.24 publication was blocked by eight lint findings in the new test/runner files after backend tests passed. Formatting/import order, explicit subprocess check behavior and strict zip were corrected. The repeatable runner now includes both Python and frontend lint gates, which pass. The corrected installer release is v0.4.25; no failed release is treated as available.
