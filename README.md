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
- **Image** — text-to-image (Krea 2, FLUX.2 Klein, SDXL), reference-image editing
  (FLUX Kontext), a Product studio with per-category shot presets, and a
  saved-character library. Folders that ship a bare fine-tuned transformer and a
  manifest naming its parts are assembled at load time against a complete
  pipeline elsewhere in the models folder.
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

## Terms, model licences and integrations

**Terms.** The application asks for agreement before anything else it does,
including downloading a model. The documents live in
`sidecar/uncloud_engine/legal/` — a core agreement shared byte-identically with
Uncloud Studio, plus a supplement about the agent specifically. They are
**unreviewed drafts**: structurally complete and accurate about how the software
behaves, but no lawyer has read them, and every fact that must not be invented —
entity, address, jurisdiction, contacts — is a visible `[[PLACEHOLDER]]`. A test
fails if one is filled in with something plausible.

Agreeing to a document grants no permission. Consent and approval are separate
systems throughout, the legal package and the permission gate never import each
other, and a test holds them apart.

**Model licences.** Nine catalogue entries have been read at source and carry
real terms with who read them and when; the rest report `unverified`, which is
neither a yes nor a no. Uncloud never blocks a download on its own reading of a
licence — it discloses, and where terms are restrictive, conditional or unread
it asks for one acknowledgement. Publishers' own gates (access requests, licence
click-throughs, auth tokens) are never routed around.

**Integrations.** `sidecar/uncloud_engine/integrations/` connects Uncloud to
things outside it. A connection is not a permission — the gate decides at the
moment of every action, and a skill inherits nothing. Credentials never enter
model context, not by redaction but by absence: nothing in the broker returns a
secret. One connector is built (a documents folder, reading Word, Excel and
PowerPoint properly); the rest are listed with what each would need.

## Licence

Not yet chosen.
