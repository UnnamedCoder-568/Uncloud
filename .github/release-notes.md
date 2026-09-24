Uncloud 0.4.8 repairs web search provider fallback, the Models page on a new
Mac, and makes local model work more dependable.

First launch now requires an explicit Models Folder choice before setup can be
completed. Downloads invalidate the model scan and every model picker refreshes
in place, so a newly downloaded model appears without closing Uncloud.

GGUF chat now includes its own llama.cpp-compatible server and works on a clean
Mac without Homebrew. Music shows an Install button for ACE-Step and streams the
setup progress inside the app; narration and speech keep their matching repair
flows instead of sending users to terminal commands.

The Thinking Orbs sphere now appears anywhere Uncloud asks the user to wait:
application and engine startup, model work, image/video/music/voice generation,
transcription, uploads, downloads, updates, imports, and other background jobs.

Web search now falls back to a second public provider when DuckDuckGo serves an
automated-request challenge page. Those challenge pages can return HTTP 200
without any results, which previously made Chat incorrectly describe a network
restriction even though the Mac had working internet access.

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

The public interface no longer shows an “Uncensored only” catalogue filter or
an image-generation control for replacing a model's text encoder.

Chat and Chisel now use the MIT-licensed Thinking Orbs animations for live
activity. The model-thinking state is shown before a response, and loading,
web work, writing and image creation have distinct accessible states. Reduced
Motion is honoured automatically.

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
