Uncloud 0.4.6 says something useful when an update cannot be installed, and
carries everything from 0.4.5: stopping a generation, running a lone quantised
transformer, and picking work back up after a phone puts the page to sleep.

Updates are signed, and the signing key was rotated during 0.4.2. A copy built
before that carries the old key and can never verify anything published since —
correct behaviour, reported as "the signature was created with a different key
than the one provided", which tells a tester nothing they can act on. It now
says the copy is too old to update itself and that downloading it once fixes it
for good, with a link to the releases page beside the message. Anyone still on
0.4.1 or earlier needs that one manual download; from 0.4.2 onwards the in-app
updater works normally.

Renders can now be stopped. Image and video jobs end at their next step — a
batch of four stops as four, queued work never starts, and a stopped clip
releases its weights. Stopping an MLX render previously did nothing at all: the
cancellation was swallowed with the progress report and the render carried on to
the end.

A fine-tuned image model shared as a single quantised transformer is no longer
listed as unsupported when the rest of its pipeline is already on the disk.
Uncloud finds a complete pipeline of the same family in the models folder and
lends the loose file its VAE, text encoder, tokenizer and scheduler.

Every view that watches a job now survives a backgrounded tab: it retries a
finished picture the browser never collected, catches up the moment the page is
visible again, and finds the render it started after a reload. The engine always
owned the work; the page can now find its way back to it.

The Windows WebView origin reaches the local engine, and the bundled uv/Python
process stays in the background — no engine terminal, and no healthy engine
reported as unavailable.

Chat now accepts supported images, readable documents and source files; offers
notes plus editable/downloadable code blocks; and hands the complete context and
selected model to Chisel. Reply images remain model-directed: a casual request
can use a quick draft, while an explicit quality or size request can invoke a
full-quality render saved to Outputs.

The interface is monochrome by default, so the only colour on screen is the work
itself. A theme and an accent are selectable, and every part of the interface —
background, sidebar, panels, lines and text — can be repainted in Settings and
reset in one press.
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
