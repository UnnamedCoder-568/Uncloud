# Installing Uncloud

Uncloud runs entirely on your own machine. Nothing is sent to a server.

> **Before you start — read this.** The desktop builds ship the *interface*, not the
> AI engine. The engine is Python and is not yet bundled, so you also need the steps
> under [Engine setup](#engine-setup). Until that is done the app will open and then
> report that the engine failed to start. This is the known gap, not a broken download.

---

## macOS

**Apple Silicon (M1–M5)** — download `Uncloud_x.y.z_aarch64.dmg`
**Intel** — download `Uncloud_x.y.z_x64.dmg`

1. Open the `.dmg` and drag **Uncloud** into Applications.
2. First launch: right-click the app → **Open** → **Open**. macOS blocks unsigned
   apps on a normal double-click; this is expected for a build that isn't
   notarised through the App Store.
3. If the app opens but the engine never starts, grant it disk access:
   **System Settings → Privacy & Security → Full Disk Access → +** → Uncloud.
   This is required whenever your models live on an external drive — a
   Finder-launched app cannot read removable volumes without it.

## Linux

Three formats are built for **x86_64 (Intel/AMD)**: `.AppImage`, `.deb`, and `.rpm`.

> **ARM machines — including NVIDIA DGX Spark — are not covered by these downloads.**
> CI builds x86_64 only, so an ARM box has to build from source:
>
> ```bash
> git clone https://github.com/aswinajith96-gif/Uncloud.git
> cd Uncloud/uncloud && npm ci && npm run tauri build
> ```
>
> The Rust and web toolchains are both ARM-native, so this works; it just takes
> about ten minutes rather than being a download.

```bash
chmod +x uncloud_*.AppImage
./uncloud_*.AppImage
```

Debian and Ubuntu can use the `.deb` instead (Fedora and RHEL: the `.rpm`):

```bash
sudo dpkg -i uncloud_*.deb
sudo apt-get install -f      # pulls any missing dependencies
```

If the window fails to appear, the usual cause is a missing webview:

```bash
sudo apt-get install libwebkit2gtk-4.1-0
```

## Windows

Download and run `Uncloud_x.y.z_x64-setup.exe`.

SmartScreen will warn about an unrecognised publisher, because the build is not
code-signed. **More info → Run anyway.**

Windows 11 already includes WebView2. On Windows 10 you may need
[the WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/).

---

## Engine setup

The AI engine needs Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. install uv
curl -LsSf https://astral.sh/uv/install.sh | sh        # macOS / Linux
# Windows (PowerShell):
#   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. clone this repository next to wherever you installed the app
git clone https://github.com/aswinajith96-gif/Uncloud.git
cd Uncloud/sidecar

# 3. install the engine
uv sync
```

### Optional extras

Each of these is only needed for the feature beside it, and each lives in its own
environment because they pin conflicting versions of torch and transformers.

```bash
# GGUF chat models
brew install llama.cpp                     # macOS
# Linux: build from https://github.com/ggml-org/llama.cpp

# audio handling
brew install ffmpeg espeak-ng              # macOS
sudo apt-get install ffmpeg espeak-ng      # Linux

# music generation
uv venv .venv-acestep --python 3.12
uv pip install --python .venv-acestep "ace-step @ git+https://github.com/ace-step/ACE-Step-1.5"

# narration — fast streaming engine
uv venv .venv-vibevoice --python 3.12
uv pip install --python .venv-vibevoice "vibevoice @ git+https://github.com/microsoft/VibeVoice"

# narration — higher-quality engine (community fork; Microsoft's repo no longer
# ships the non-streaming model)
uv venv .venv-vibevoice-hq --python 3.12
uv pip install --python .venv-vibevoice-hq "vibevoice @ git+https://github.com/vibevoice-community/VibeVoice"

# browser control for the agent
uv run playwright install chromium
```

---

## First run

1. Open Uncloud and choose a folder for your models. Point it at an existing
   folder if you already have `.gguf` or diffusers models — they'll be detected.
2. Open **Models** and download something to start with. Good first picks:
   - **Chat** — Gemma 4 12B QAT (11 GB), which can also read images
   - **Images** — Krea 2 Turbo Q4 (15 GB)
3. Everything else is optional and can be added later.

## Hardware

| Memory | What's comfortable |
| --- | --- |
| 16 GB | Chat models up to ~9B, small image models |
| 24 GB | One large model at a time — a 27B chat model *or* an image model |
| 32 GB+ | Larger models, more headroom for several at once |

Uncloud unloads the chat model before generating images, video, music or
narration, because on a 24 GB machine they cannot coexist. Exceeding physical
memory doesn't fail gracefully — it drops into swap and slows down by an order
of magnitude.

Apple Silicon uses MLX where possible. On Linux and Windows those models are
unavailable and the equivalent PyTorch paths are used instead; with an NVIDIA
GPU those are typically faster than the Apple ones.

## Where your files go

| | |
| --- | --- |
| Settings | `~/.uncloud/settings.json` |
| Generated output | `~/.uncloud/outputs/` |
| Saved characters | `~/.uncloud/characters/` |
| Saved voices | `~/.uncloud/voices/` |
| Agent workspace | `~/.uncloud/workspace/` |
| Models | wherever you chose during setup |
