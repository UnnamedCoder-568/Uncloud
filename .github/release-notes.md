Uncloud 0.4.10 — macOS Apple silicon, Linux x64 and Windows x64

- Chat searches before answering explicit web requests and current-information questions, without relying on the model to emit a tool marker. Follow-up requests retain the original topic.
- Search rejects clearly unrelated results and retries with the topic words. Lookup failures are shown directly instead of letting the model invent an answer from outdated memory.
- Windows includes a checksum-verified native CPU chat runtime. Installation no longer needs a C/C++ compiler, and the packaged runtime is checked before publication.
- Includes v0.4.9 improvements: clearer internet permission recovery, a compact Chat settings menu, 4:3 image presets with custom dimensions, and a unified startup screen with Continue below the logo and animation.

Existing internet permission choices are preserved. If access is set to Never, use Chat settings to enable session-based internet approval.
