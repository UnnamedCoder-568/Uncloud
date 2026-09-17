# Uncloud

Uncloud is a local-first AI studio for chat, image generation, video, voice,
model management, and agent workflows. The desktop interface runs on your
machine and talks to a private Python engine on localhost.

Created by Aswin Ajith.

> **Current release:** v0.4.5. Windows, Linux, and Apple-silicon macOS packages
> are intended for external testing and are not code-signed or notarised.

## Download

| Platform | Download | Run |
| --- | --- | --- |
| Windows 10/11 x64 | [Uncloud-Windows-x64.exe](https://github.com/UnnamedCoder-568/Uncloud/releases/download/v0.4.5/Uncloud-Windows-x64.exe) | Open the installer, then launch Uncloud from the Start menu. |
| Linux x64 | [Uncloud-Linux-x64.AppImage](https://github.com/UnnamedCoder-568/Uncloud/releases/download/v0.4.5/Uncloud-Linux-x64.AppImage) | Make it executable and run it. |
| macOS Apple Silicon | [Uncloud-macOS-Apple-Silicon.dmg](https://github.com/UnnamedCoder-568/Uncloud/releases/download/v0.4.5/Uncloud-macOS-Apple-Silicon.dmg) | Open the DMG, then drag Uncloud to Applications. |

All release downloads and SHA-256 checksums are also on the
[Releases page](https://github.com/UnnamedCoder-568/Uncloud/releases).

### Intel Macs are not supported

The `Uncloud-macOS-Intel.dmg` attached to the older v0.3.0-test.2 release
installs, and then its
engine cannot finish setting itself up. PyTorch published its last macOS
x86_64 build at 2.2.2 and the engine needs 2.13 or newer, so there is no
version of the dependency to install on an Intel Mac. The download has been
withdrawn from this table rather than left to fail on somebody's machine, and
the build target has been removed so no future release produces one.

Apple Silicon is unaffected — it never used that code path.

On Linux:

```bash
chmod +x Uncloud-Linux-x64.AppImage
./Uncloud-Linux-x64.AppImage
```

Windows SmartScreen may show **Unknown publisher** because this test build is
unsigned. Choose **More info → Run anyway** only if the file came from this
repository's release page and its checksum matches `SHA256SUMS.txt`.

## First launch

No Python, Node.js, Rust, or uv installation is required. The desktop package
contains:

- the Uncloud interface;
- the complete engine source;
- a verified, pinned copy of uv for the target platform.

The first launch needs an internet connection. Uncloud uses its bundled uv to
download Python 3.12 and the locked engine dependencies into `~/.uncloud/engine`.
This is a one-time download of several gigabytes. Model weights are separate and
are downloaded only when you choose them in the Models tab.

See [INSTALL.md](INSTALL.md) for platform troubleshooting and source-development
instructions.

## What is included

- Local chat with GGUF models through llama.cpp and MLX models on Apple Silicon
- Text-to-image, reference editing, product imagery, video, music, and narration
- Local model discovery and resumable model downloads
- Agent tools with explicit permission prompts and an audit trail
- Optional integrations and MCP servers

Feature availability depends on the selected model and hardware. Some optional
runtimes, such as llama.cpp for GGUF chat, are installed separately; the desktop
application and its core engine do not require a development environment.

## Report a problem

Use the [GitHub issue tracker](https://github.com/UnnamedCoder-568/Uncloud/issues).
Include:

- Windows, Linux, or macOS version;
- CPU, GPU, and memory;
- the downloaded filename;
- what you expected, what happened, and steps to reproduce;
- the final setup error or relevant log tail, with tokens and personal data removed.

## Architecture

| Part | Stack | Purpose |
| --- | --- | --- |
| `uncloud/` | Tauri 2, React, Vite | Native desktop shell and interface |
| `sidecar/` | Python 3.12, FastAPI, uv | Local inference engine and model tooling |

Tauri starts the engine on a random localhost port and passes a new
authentication token for each launch. Release packages contain the engine as
resources rather than freezing the full ML stack into a multi-gigabyte
installer.

## Licence

A source licence has not yet been selected. Until one is added, copyright law
applies by default. The release is provided for testing, not as a grant to
redistribute or modify the source.
