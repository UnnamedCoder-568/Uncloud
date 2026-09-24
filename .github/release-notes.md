Uncloud 0.4.7 repairs the Models page on a new Mac and makes local model work
more dependable.

If macOS refuses access to the selected models folder, the bundled download
catalogue now remains available and the installed-model list explains how to
recover by choosing a dedicated folder. Previously both requests failed with
the unhelpful message `TypeError: Load failed`, leaving the Models page empty.

FLUX.1 Kontext checkpoints saved in the older numbered-shard MLX layout are now
found and offered for reference-image editing. A completed model download also
appears in the library immediately.

Chisel now repairs malformed planner output once, validates task dependencies,
and refuses to execute reasoning text as a tool plan. Failed dependencies are
reported instead of leaving tasks silently pending. Chat no longer claims that
it created a file when no file tool ran, and supported image attachments reach
vision-capable chat models.

Chat now stops and explains a local model that produces no output for two
minutes, including after a web lookup, instead of spinning forever. The pending
reply indicator also keeps its proper circular shape and generation errors no
longer leave an empty visual artifact in the conversation.

Web lookups use DuckDuckGo's supported no-JavaScript GET page, avoiding the
denials returned by its older automated POST endpoint. Chisel tool selections
now have a visible border and checkmark in Settings.

The optional writing sound now remains audible even when a fast model delivers
its reply in one large chunk, and its synthesis resembles a soft modern inkjet
feed instead of an old dot-matrix clatter.

Links can leave the desktop app correctly, model cards are easier to read, and
the Models page links to publisher pages and alternative model hubs.

The Windows x64 installer, Linux x64 AppImage, and Apple-silicon macOS DMG are
built on GitHub-hosted native runners. CI tests the frontend, Python engine and
Rust desktop shell, verifies the bundled engine and uv runtime, and signs the
updater artifacts before publication.

Intel Macs remain unsupported because the engine's current PyTorch dependency
does not publish macOS x86_64 packages.

The installers are not OS code-signed or notarised, so Windows SmartScreen or
macOS Gatekeeper may display a warning. Checksums are provided in
`SHA256SUMS.txt`.
