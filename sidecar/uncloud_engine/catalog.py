from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CatalogEntry:
    id: str
    name: str
    category: str  # text | image | video | voice-stt | voice-tts
    engine: str  # gguf | mlx | mflux | diffusers | faster-whisper | kokoro
    repo: str  # Hugging Face repo id
    files: list[str] = field(default_factory=list)  # specific files to pull; empty = whole repo
    size_gb: float = 0.0
    description: str = ""
    tags: list[str] = field(default_factory=list)
    context_length: int | None = None
    offline_capable: bool = True
    single_file: bool = False  # for engine="diffusers": load via from_single_file instead of from_pretrained
    note: str | None = None  # shown in the UI — hardware caveats, licensing, etc.
    mflux_cli: str = "mflux-generate"  # for engine="mflux": which mflux CLI binary knows this architecture
    # Which mflux base config to build. One CLI covers a whole family — the
    # Klein entry point serves both 4B and 9B — and loading a 4B checkpoint
    # against the 9B config fails on tensor shape. Set it where they differ.
    mflux_base: str | None = None
    fixup: str | None = None  # for engine="mflux": post-download layout fix to apply (see downloader.py)
    # What this model can actually do. Drives which Image sub-tabs offer it.
    #   text2img  — prompt only
    #   edit      — takes a reference image + an instruction (Kontext-style)
    #   inpaint   — takes a reference image + a mask
    capabilities: list[str] = field(default_factory=lambda: ["text2img"])


CATALOG: list[CatalogEntry] = [
    # ---- Small and current: the point of these is fitting comfortably ----
    CatalogEntry(
        id="z-image-turbo-mlx",
        name="Z-Image Turbo (MLX)",
        category="image", engine="mflux",
        repo="filipstrand/Z-Image-Turbo-mflux-4bit",
        size_gb=5.9,
        description="6B model reaching FLUX-class photorealism in 8 steps. Ships already "
                    "quantised, so it loads in seconds and stays resident.",
        tags=["fast", "recommended", "apple-silicon"],
        mflux_cli="mflux-generate-z-image",
    ),
    CatalogEntry(
        id="flux2-klein-9b-uncensored-encoder",
        name="FLUX.2 Klein 9B — Uncensored Text Encoder",
        category="component", engine="text-encoder",
        repo="ponpoke/flux2-klein-9b-uncensored-text-encoder",
        size_gb=4.7,
        description="Drop-in replacement for Klein's Qwen3 text encoder. Klein's "
                    "restraint lives in that encoder, so swapping it is what actually "
                    "changes what the model will render — and it is 4.7GB against 15GB.",
        tags=["uncensored"],
        note="A component, not a model. Pair it with FLUX.2 Klein 9B.",
    ),
    CatalogEntry(
        id="flux2-klein-4b-mlx",
        name="FLUX.2 Klein 4B (MLX)",
        category="image", engine="mflux",
        repo="Runpod/FLUX.2-klein-4B-mflux-4bit",
        size_gb=4.6,
        description="The small Klein, already quantised. Less capable than the 9B on "
                    "complex scenes, and roughly five times quicker per step.",
        tags=["fast", "recommended", "apple-silicon"],
        mflux_cli="mflux-generate-flux2-klein",
        mflux_base="flux2_klein_4b",
    ),
    # ---- Text: general purpose, GGUF (llama.cpp, portable, CPU/Metal) ----
    CatalogEntry(
        id="llama-3.1-8b-instruct-gguf",
        name="Llama 3.1 8B Instruct",
        category="text", engine="gguf",
        repo="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        files=["Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"],
        size_gb=4.9, context_length=128000,
        description="Meta's general-purpose chat model. Strong all-rounder.",
        tags=["general", "recommended"],
    ),
    CatalogEntry(
        id="qwen2.5-7b-instruct-gguf",
        name="Qwen2.5 7B Instruct",
        category="text", engine="gguf",
        repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
        files=["Qwen2.5-7B-Instruct-Q4_K_M.gguf"],
        size_gb=4.7, context_length=32768,
        description="Fast, strong reasoning and coding for its size.",
        tags=["general", "coding", "recommended"],
    ),
    CatalogEntry(
        id="deepseek-r1-distill-8b-gguf",
        name="DeepSeek R1 Distill 8B",
        category="text", engine="gguf",
        repo="unsloth/DeepSeek-R1-Distill-Llama-8B-GGUF",
        files=["DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf"],
        size_gb=4.9, context_length=32768,
        description="Reasoning-tuned model that shows its chain of thought.",
        tags=["reasoning"],
    ),
    CatalogEntry(
        id="mistral-nemo-12b-gguf",
        name="Mistral Nemo 12B Instruct",
        category="text", engine="gguf",
        repo="bartowski/Mistral-Nemo-Instruct-2407-GGUF",
        files=["Mistral-Nemo-Instruct-2407-Q4_K_M.gguf"],
        size_gb=7.5, context_length=128000,
        description="Large context window, good multilingual support.",
        tags=["general", "multilingual"],
    ),
    # ---- Text + vision: models with an image encoder built in ----
    # These serve through mlx_vlm rather than mlx_lm, so one loaded model both
    # reasons and reads screenshots. "QAT" means the model was trained while
    # simulating 4-bit rounding, so it loses far less than a naive squeeze.
    CatalogEntry(
        id="gemma-4-26b-a4b-qat-mlx-q4",
        name="Gemma 4 26B-A4B (MLX, QAT Q4)",
        category="text", engine="mlx-vlm",
        repo="mlx-community/gemma-4-26B-A4B-it-qat-4bit",
        size_gb=15.6, context_length=131072,
        description="Mixture-of-experts with vision built in: 26B total, ~4B active. Reasons and sees, at small-model speed.",
        tags=["general", "vision", "reasoning", "apple-silicon", "recommended"],
        capabilities=["text2img"],
        note="Has an image encoder — Uncloud serves it through mlx-vlm so it can read screenshots and photos.",
    ),
    CatalogEntry(
        id="gemma-4-12b-qat-mlx-q4",
        name="Gemma 4 12B (MLX, QAT Q4)",
        category="text", engine="mlx-vlm",
        repo="mlx-community/gemma-4-12B-it-qat-4bit",
        size_gb=11.0, context_length=131072,
        description="Smaller vision-capable model. Leaves headroom to keep an image model loaded alongside it.",
        tags=["general", "vision", "fast", "apple-silicon"],
        capabilities=["text2img"],
    ),
    # ---- Text: MLX, sized for a 24GB Mac ----
    # Budget note: macOS plus Uncloud leave roughly 17-18GB usable, so anything past
    # ~18GB will swap. "A3B" models are mixture-of-experts with only 3B parameters
    # active per token — large-model quality at small-model speed.
    CatalogEntry(
        id="qwen3.8-27b-mlx-q4",
        name="Qwen3.8 27B (MLX, Q4)",
        category="text", engine="mlx",
        repo="mlx-community/Qwen3.8-27B-4bit",
        size_gb=16.1, context_length=32768,
        description="Strongest general reasoning that fits comfortably in 24GB. The daily driver for agent work.",
        tags=["general", "reasoning", "apple-silicon", "recommended"],
        note="~16GB resident — close other heavy apps and expect image models to be unloaded while this runs.",
    ),
    CatalogEntry(
        id="qwen3-coder-30b-a3b-mlx-q4",
        name="Qwen3 Coder 30B-A3B (MLX, Q4 DWQ)",
        category="text", engine="mlx",
        repo="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
        size_gb=17.2, context_length=262144,
        description="Mixture-of-experts coding model: 30B total, 3B active. Strong C++ — a good fit for Unreal Engine work.",
        tags=["coding", "apple-silicon", "recommended"],
        note="~17GB resident. DWQ quantization retains noticeably more quality than plain Q4.",
    ),
    CatalogEntry(
        id="devstral-small-24b-mlx-q4",
        name="Devstral Small 24B (MLX, Q4)",
        category="text", engine="mlx",
        repo="mlx-community/Devstral-Small-2-24B-Instruct-2512-4bit",
        size_gb=15.1, context_length=131072,
        description="Mistral's agentic coding model, built for multi-file codebase edits rather than snippet completion.",
        tags=["coding", "agentic", "apple-silicon"],
    ),
    CatalogEntry(
        id="qwen3.5-9b-mlx-q4",
        name="Qwen3.5 9B (MLX, Q4)",
        category="text", engine="mlx",
        repo="mlx-community/Qwen3.5-9B-MLX-4bit",
        size_gb=6.0, context_length=32768,
        description="Fast general-purpose model, small enough to stay loaded alongside an image model.",
        tags=["general", "fast", "apple-silicon"],
    ),
    CatalogEntry(
        id="llama-3.1-8b-instruct-mlx",
        name="Llama 3.1 8B Instruct (MLX)",
        category="text", engine="mlx",
        repo="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        size_gb=4.5, context_length=128000,
        description="Apple Silicon-optimized build. Faster than GGUF on this Mac.",
        tags=["general", "apple-silicon", "recommended"],
    ),
    CatalogEntry(
        id="qwen2.5-7b-instruct-mlx",
        name="Qwen2.5 7B Instruct (MLX)",
        category="text", engine="mlx",
        repo="mlx-community/Qwen2.5-7B-Instruct-4bit",
        size_gb=4.3, context_length=32768,
        description="Apple Silicon-optimized build for maximum throughput.",
        tags=["general", "coding", "apple-silicon"],
    ),
    # ---- Text: uncensored / abliterated ----
    CatalogEntry(
        id="llama-3.1-8b-lexi-uncensored-gguf",
        name="Llama 3.1 8B Lexi Uncensored",
        category="text", engine="gguf",
        repo="bartowski/Llama-3.1-8B-Lexi-Uncensored-V2-GGUF",
        files=["Llama-3.1-8B-Lexi-Uncensored-V2-Q4_K_M.gguf"],
        size_gb=4.9, context_length=128000,
        description="Refusal-ablated fine-tune. No built-in content filtering.",
        tags=["uncensored"],
    ),
    CatalogEntry(
        id="qwen2.5-7b-abliterated-gguf",
        name="Qwen2.5 7B Instruct Abliterated",
        category="text", engine="gguf",
        repo="mradermacher/Qwen2.5-7B-Instruct-abliterated-GGUF",
        files=["Qwen2.5-7B-Instruct-abliterated.Q4_K_M.gguf"],
        size_gb=4.7, context_length=32768,
        description="Refusal-direction ablated. No built-in content filtering.",
        tags=["uncensored"],
    ),
    # ---- Image diffusion ----
    CatalogEntry(
        id="flux1-kontext-dev-mlx-q4",
        name="FLUX.1 Kontext (MLX, Q4)",
        category="image", engine="mflux",
        repo="akx/FLUX.1-Kontext-dev-mflux-4bit",
        size_gb=9.6,
        description=(
            "Reference-image editing model. Give it a photo plus an instruction and it "
            "re-renders the scene while keeping the subject's identity and fine detail. "
            "Powers Product, Edit and Characters."
        ),
        tags=["recommended", "apple-silicon", "reference"],
        mflux_cli="mflux-generate-kontext",
        capabilities=["edit", "reference"],
    ),
    CatalogEntry(
        id="krea-2-turbo-mlx-q4",
        name="Krea 2 Turbo (MLX, Q4)",
        category="image", engine="mflux",
        repo="mflux-community/krea-2-turbo-mflux-q4",
        size_gb=15.0,
        description="Krea's aesthetic-first 12.9B DiT model, 4-bit quantized for Apple Silicon via mflux. Best fit for 16-24GB Macs.",
        tags=["recommended", "apple-silicon", "fast"],
        mflux_cli="mflux-generate-krea2",
        fixup="flat-transformer-shards",
    ),
    CatalogEntry(
        id="krea-2-turbo-mlx",
        name="Krea 2 Turbo (MLX, Q8)",
        category="image", engine="mflux",
        repo="mflux-community/krea-2-turbo-mflux-q8",
        size_gb=22.2,
        description="Same model at 8-bit — higher fidelity, but ~22GB resident. Only worth it on 32GB+ Macs.",
        tags=["quality", "apple-silicon"],
        note="~22GB resident. Measured on a 24GB M5: 80s per step against 5s for Klein 4B, "
     "because it does not fit and pages every step. One 1024x1024 image took 11 minutes. "
     "Needs 32GB+; on 24GB take the Q4 build or a smaller model.",
        mflux_cli="mflux-generate-krea2",
        fixup="flat-transformer-shards",
    ),
    CatalogEntry(
        id="flux1-schnell",
        name="FLUX.1 [schnell]",
        category="image", engine="diffusers",
        repo="black-forest-labs/FLUX.1-schnell",
        size_gb=23.0,
        description="State-of-the-art open image model, 1-4 step distilled — fast.",
        tags=["fast"],
    ),
    CatalogEntry(
        id="flux1-dev",
        name="FLUX.1 [dev]",
        category="image", engine="diffusers",
        repo="black-forest-labs/FLUX.1-dev",
        size_gb=23.0,
        description="Highest quality FLUX variant, more steps, non-commercial license.",
        tags=["quality"],
    ),
    CatalogEntry(
        id="sdxl-base-1.0",
        name="Stable Diffusion XL Base 1.0",
        category="image", engine="diffusers",
        repo="stabilityai/stable-diffusion-xl-base-1.0",
        size_gb=6.9,
        description="Widely supported, huge LoRA/community ecosystem.",
        tags=["general"],
    ),
    CatalogEntry(
        id="sd3.5-medium",
        name="Stable Diffusion 3.5 Medium",
        category="image", engine="diffusers",
        repo="stabilityai/stable-diffusion-3.5-medium",
        size_gb=10.0,
        description="Latest-gen Stability model, strong prompt adherence.",
        tags=["quality"],
    ),
    CatalogEntry(
        id="qwen-image",
        name="Qwen-Image",
        category="image", engine="diffusers",
        repo="Qwen/Qwen-Image",
        size_gb=20.0,
        description="Strong text rendering inside generated images.",
        tags=["quality"],
    ),
    CatalogEntry(
        id="pony-diffusion-v6-xl",
        name="Pony Diffusion V6 XL",
        category="image", engine="diffusers", single_file=True,
        repo="LyliaEngine/Pony_Diffusion_V6_XL",
        files=["ponyDiffusionV6XL_v6StartWithThisOne.safetensors"],
        size_gb=6.94,
        description="SDXL finetune trained across a wide safe/questionable/explicit range. Strong anime/anthro capability.",
        tags=["uncensored"],
    ),
    # ---- Video diffusion ----
    CatalogEntry(
        id="ltx-video",
        name="LTX-Video",
        category="video", engine="diffusers",
        repo="Lightricks/LTX-Video",
        size_gb=9.0,
        description="Fast real-time-ish video generation, good for iteration.",
        tags=["fast", "recommended"],
    ),
    CatalogEntry(
        id="cogvideox-5b",
        name="CogVideoX-5B",
        category="video", engine="diffusers",
        repo="THUDM/CogVideoX-5b",
        size_gb=11.0,
        description="High quality text/image-to-video.",
        tags=["quality"],
    ),
    CatalogEntry(
        id="wan2.1-t2v-1.3b",
        name="Wan2.1 T2V 1.3B",
        category="video", engine="diffusers",
        repo="Wan-AI/Wan2.1-T2V-1.3B",
        size_gb=6.0,
        description="Lightweight text-to-video, runs on smaller GPUs/unified memory.",
        tags=["fast"],
    ),
    # ---- Voice: speech-to-text ----
    CatalogEntry(
        id="whisper-large-v3",
        name="Whisper Large v3",
        category="voice-stt", engine="faster-whisper",
        repo="Systran/faster-whisper-large-v3",
        size_gb=3.1,
        description="Best accuracy transcription, 99 languages.",
        tags=["recommended"],
    ),
    CatalogEntry(
        id="whisper-small",
        name="Whisper Small",
        category="voice-stt", engine="faster-whisper",
        repo="Systran/faster-whisper-small",
        size_gb=0.5,
        description="Fast, low-resource transcription.",
        tags=["fast"],
    ),
    # ---- Voice: text-to-speech ----
]

# Kokoro TTS isn't in the downloadable catalog above: the `kokoro` package always
# fetches its ~350MB of weights itself via huggingface_hub on first use (it doesn't
# accept a plain local directory), so it's offered directly in the Voice tab instead
# of through the Models-tab download flow the rest of the catalog uses.


def get_catalog() -> list[CatalogEntry]:
    return CATALOG


def get_entry(catalog_id: str) -> CatalogEntry | None:
    return next((e for e in CATALOG if e.id == catalog_id), None)
