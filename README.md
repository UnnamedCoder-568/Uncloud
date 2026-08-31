# Uncloud

Local-first AI studio. Chat, image generation, product photography, voice and an
agent — running on your own machine, against your own model files, offline if you
want it to be.

## What's inside

| Part | Stack | Job |
| --- | --- | --- |
| `uncloud/` | Tauri 2 + React + Vite + Tailwind 4 | Desktop shell and UI |
| `sidecar/` | Python 3.12 + FastAPI, managed by `uv` | Inference engine, agent, model management |

The Rust shell owns the window and spawns the Python engine on a random localhost
port, handing it a per-launch auth token. Everything heavy — MLX, llama.cpp,
diffusers, Playwright — lives in the sidecar.

## Features

- **Chat** — GGUF via llama.cpp, or MLX for Apple Silicon. Optional voice in/out.
- **Models** — browse a curated catalog, download into a folder you choose, with
  resumable transfers.
- **Image** — text-to-image (Krea 2, SDXL), reference-image editing (FLUX Kontext),
  a Product studio with per-category shot presets, and a saved-character library.
- **Agent** — plans a task graph with the loaded model and executes it against 24
  tools: shell, filesystem, web search and reading, full browser control, vision,
  image generation, and persistent plan/memory.
- **Voice** — transcription via faster-whisper, speech via Kokoro.

## Requirements

- macOS on Apple Silicon (Linux and Windows build via CI but are untested)
- [`uv`](https://docs.astral.sh/uv/) for the Python engine
- `llama.cpp` for GGUF models — `brew install llama.cpp`
- `ffmpeg` for audio — `brew install ffmpeg`

## Running in development

```bash
cd sidecar && uv sync          # Python engine
cd ../uncloud && npm install   # frontend
npm run tauri dev
```

## Known limitations

- **The Python engine is not bundled.** The desktop build launches it through `uv`
  from the source tree, so a packaged `.app` only runs on a machine that has this
  repository and `uv` present. Shipping a standalone binary needs the engine frozen
  (PyInstaller) and registered as a Tauri sidecar — that work is not done.
- **Memory.** A 24 GB machine fits roughly one large model at a time. The engine
  unloads the chat model before image generation for this reason. Reference editing
  is capped near 1 MP; past that, peak memory tips into swap and generation time
  collapses (measured: 20 s/step at 0.5 MP versus 563 s/step at 4.3 MP).
- **Product shots** reproduce a garment's *style* faithfully but not its exact
  stitch layout, and quality tracks the reference photo closely.
- **Vision** requires a model with an image encoder (Gemma 4, Qwen3.8) served
  through `mlx-vlm`; text-only models return a clear error.

## Licence

Not yet chosen.
