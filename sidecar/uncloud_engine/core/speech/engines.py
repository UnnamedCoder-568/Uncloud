"""Which speech engines exist, how to recognise their weights, and their voices.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Standard library only.

Recognition is by the files a folder holds, never by its name. A folder
called "chatterbox-tts" that holds Bark is Bark, and one renamed "My voice"
that holds Chatterbox is still Chatterbox. The worker then loads exactly the
variant recognised here, so what the interface offers and what runs cannot
disagree.

What an engine NEEDS installed is written down here too, because both
products build an environment from it: an engine whose requirements live only
in a document is described, not shipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Control:
    """One adjustable setting, with the range the engine actually accepts."""

    id: str
    label: str
    minimum: float
    maximum: float
    default: float
    step: float
    hint: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "min": self.minimum,
                "max": self.maximum, "default": self.default, "step": self.step,
                "hint": self.hint}


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    summary: str
    #: What its environment installs. Pinned where the engine pins.
    requirements: tuple[str, ...]
    #: Import names that prove an interpreter already satisfies it.
    modules: tuple[str, ...]
    #: Speaks in the voice of a reference recording.
    clones: bool = False
    #: Re-voices a recording (voice to voice).
    converts: bool = False
    #: The longest piece said in one generation; 0 means any length.
    chunk_chars: int = 0
    controls: tuple[Control, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "summary": self.summary,
                "clones": self.clones, "converts": self.converts,
                "controls": [c.to_dict() for c in self.controls]}


ENGINES: dict[str, Engine] = {
    "kokoro": Engine(
        id="kokoro", label="Kokoro",
        summary="Small and quick. Natural preset voices; ideal for replies read aloud.",
        requirements=("kokoro>=0.9.4", "soundfile>=0.13"),
        modules=("kokoro", "soundfile"),
        controls=(Control("speed", "Speed", 0.5, 2.0, 1.0, 0.05),),
    ),
    "chatterbox": Engine(
        id="chatterbox", label="Chatterbox",
        summary="Expressive, and speaks in any voice from a short recording. "
                "Up to 23 languages with the multilingual weights.",
        # The released package pins torch 2.6 and diffusers 0.29, which is why
        # it always gets an environment of its own.
        # setuptools: its watermarker imports pkg_resources, which a fresh uv
        # environment lacks and setuptools 81 removed. Without it the import is
        # swallowed and the model fails to construct.
        requirements=("chatterbox-tts==0.1.7", "setuptools<81"),
        modules=("chatterbox",),
        clones=True, converts=True, chunk_chars=300,
        controls=(
            Control("exaggeration", "Expressiveness", 0.25, 2.0, 0.5, 0.05,
                    "Higher is more dramatic; very high can become unstable."),
            Control("cfg_weight", "Pace", 0.0, 1.0, 0.5, 0.05,
                    "Lower speaks more slowly and deliberately."),
            Control("temperature", "Variation", 0.1, 1.5, 0.8, 0.05),
        ),
    ),
    "bark": Engine(
        id="bark", label="Bark",
        summary="Characterful and unpredictable: can laugh, sigh and hesitate. "
                "Slow, and each generation sounds a little different.",
        requirements=("transformers>=4.50", "torch>=2.6", "soundfile>=0.13"),
        modules=("transformers", "torch", "soundfile"),
        chunk_chars=180,
        controls=(Control("temperature", "Variation", 0.1, 1.2, 0.7, 0.05),),
    ),
}

#: The multilingual Chatterbox weights' languages, as the package declares them.
CHATTERBOX_LANGUAGES = {
    "ar": "Arabic", "da": "Danish", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "ms": "Malay", "nl": "Dutch",
    "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ru": "Russian",
    "sv": "Swedish", "sw": "Swahili", "tr": "Turkish", "zh": "Chinese",
}

#: Kokoro voice names start with a language letter. Japanese and Mandarin need
#: extra language packages the engine does not install, so they are not offered.
KOKORO_LANGUAGES = {
    "a": "American English", "b": "British English", "e": "Spanish", "f": "French",
    "h": "Hindi", "i": "Italian", "p": "Brazilian Portuguese",
}

_BARK_LANGUAGES = {
    "en": "English", "de": "German", "es": "Spanish", "fr": "French", "hi": "Hindi",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "pl": "Polish",
    "pt": "Portuguese", "ru": "Russian", "tr": "Turkish", "zh": "Chinese",
}


@dataclass(frozen=True)
class Variant:
    """One loadable set of weights inside a folder."""

    id: str
    label: str
    languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recognised:
    engine: str
    variants: tuple[Variant, ...] = ()
    #: Can re-voice a recording with these weights.
    converts: bool = False

    def to_dict(self) -> dict:
        names = {"chatterbox": CHATTERBOX_LANGUAGES, "kokoro": KOKORO_LANGUAGES,
                 "bark": _BARK_LANGUAGES}.get(self.engine, {})
        return {"engine": self.engine, "converts": self.converts,
                "variants": [{"id": v.id, "label": v.label,
                              "languages": [{"id": code, "name": names.get(code, code)}
                                            for code in v.languages]}
                             for v in self.variants]}


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    language: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "language": self.language,
                "notes": self.notes}


def _has(folder: Path, *names: str) -> bool:
    return all((folder / n).is_file() for n in names)


def _architectures(folder: Path) -> list[str]:
    try:
        data = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = data.get("architectures") if isinstance(data, dict) else None
    return [a for a in found if isinstance(a, str)] if isinstance(found, list) else []


def chatterbox_variants(folder: Path) -> tuple[Variant, ...]:
    """Newest first, so the first is the sensible default."""
    out: list[Variant] = []
    shared = ("ve.pt", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json")
    languages = tuple(CHATTERBOX_LANGUAGES)
    if _has(folder, "t3_mtl23ls_v3.safetensors", *shared):
        out.append(Variant("multilingual-v3", "Multilingual V3", languages))
    if _has(folder, "t3_mtl23ls_v2.safetensors", *shared):
        out.append(Variant("multilingual-v2", "Multilingual V2", languages))
    if _has(folder, "t3_cfg.safetensors", "ve.safetensors", "s3gen.safetensors",
            "tokenizer.json"):
        out.append(Variant("english", "English", ("en",)))
    return tuple(out)


def recognise(folder: Path) -> Recognised | None:
    """What speech engine these weights belong to, or None."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    variants = chatterbox_variants(folder)
    converts = _has(folder, "s3gen.safetensors")
    if variants or (converts and _has(folder, "conds.pt")):
        return Recognised("chatterbox", variants, converts=converts)
    if "BarkModel" in _architectures(folder):
        return Recognised("bark", (Variant("bark", "Bark", tuple(_BARK_LANGUAGES)),))
    if (folder / "voices").is_dir() and any(folder.glob("kokoro*.pth")):
        return Recognised("kokoro", (Variant("kokoro", "Kokoro",
                                             tuple(KOKORO_LANGUAGES)),))
    return None


def presets(engine: str, folder: Path) -> list[Preset]:
    """The voices that ship with the weights. Read from the folder, so the list
    is what is actually on disk rather than what a model card once promised."""
    folder = Path(folder)
    if engine == "kokoro":
        out = []
        for f in sorted((folder / "voices").glob("*.pt")):
            lang, gender = f.stem[:1], f.stem[1:2]
            if lang not in KOKORO_LANGUAGES or "_" not in f.stem:
                continue
            name = f.stem.split("_", 1)[1].replace("_", " ").title()
            out.append(Preset(f.stem, name, KOKORO_LANGUAGES[lang],
                              {"f": "female", "m": "male"}.get(gender, "")))
        return out
    if engine == "bark":
        try:
            table = json.loads((folder / "speaker_embeddings_path.json")
                               .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for key in sorted(k for k in table if k != "repo_or_path"):
            # The v2 prompts supersede the originals; offering both doubles the
            # list with near-duplicates.
            if not key.startswith("v2/") and f"v2/{key}" in table:
                continue
            stem = key.removeprefix("v2/")
            lang, _, number = stem.partition("_speaker_")
            if number:
                out.append(Preset(key, f"Speaker {number}",
                                  _BARK_LANGUAGES.get(lang, lang.upper())))
            else:
                out.append(Preset(key, stem.replace("_", " ").title()))
        return out
    if engine == "chatterbox" and _has(folder, "conds.pt"):
        return [Preset("default", "Built-in voice", notes="or any recording you add")]
    return []
