Uncloud 0.4.4 hardens chat and generation across desktop and paired local-network
devices. Replies and long-running image jobs now stay owned by the engine when a
phone browser is backgrounded, conversations and outputs are isolated per paired
device, and stale work can no longer land in a different chat.

This hotfix allows the production Windows WebView origin to reach the local
engine and keeps the bundled uv/Python process in the background. Windows no
longer opens an engine terminal or reports a healthy engine as unavailable.

Chat now accepts supported images, readable documents and source files; offers
notes plus editable/downloadable code blocks; and hands the complete context and
selected model to Chisel. Reply images remain model-directed: a casual request
can use a quick draft, while an explicit quality or size request can invoke a
full-quality render saved to Outputs.

The interface is monochrome by default with user-selectable theme and accent.
Chat can also, entirely optionally, clatter like an old dot-matrix printer while
it writes a visible reply. The sound remains off by default and stops for model
loading, thinking, searches, cancellation, errors and navigation.
This release also fixes Windows OAuth/MCP configuration storage, model-placement
estimates, sidecar cleanup, voice status polling, and Stop/Unload handling for
speech, music and narration.

The Windows x64 installer, Linux x64 AppImage, and Apple-silicon macOS DMG are
freshly built on GitHub-hosted native runners. Before publication, CI tests the
frontend, Python engine, and Rust desktop shell; verifies the bundled engine and
uv runtime; and inspects each packaged application.

Intel Macs are not supported because the engine's current PyTorch dependency no
longer provides macOS x86_64 packages.

Please report defects through the repository's
[issue tracker](https://github.com/UnnamedCoder-568/Uncloud/issues), including
your operating system, hardware, and the steps that reproduced the problem.

The installers are not OS code-signed or notarised, so Windows SmartScreen or
macOS Gatekeeper may display a warning. Checksums for every download are in
`SHA256SUMS.txt`.
