"""Uncloud's catalogue and library, described in the shared vocabulary.

A projection, not a migration. `CatalogEntry` and `LocalModel` keep their exact
shapes on disk and in the API; nothing a user has downloaded moves, and no
existing endpoint changes. What this adds is a second way to READ them — the
one `foundation.capability` defines — so routing, effort translation and
feasibility can be written once against both products.

Two honest gaps, recorded here rather than papered over:

**Uncloud's catalogue carries no licence data at all.** Thirty-three entries,
none with terms, one mentioning a restriction in its prose description. Every
profile therefore reports `UNVERIFIED`, which is the truth: nobody has read
them. It must not be rendered as permission, and populating it properly is its
own piece of work.

**Capability is inferred from `category` and `engine`.** That inference is
sound for what the catalogue holds today — a `category="image"` entry with
`mflux` behind it does generate images — but it is inference, and a new
category with no mapping raises rather than guessing at something plausible.
"""

from __future__ import annotations

from .catalog import CatalogEntry
from .foundation import Capability, Cost, Licence, Modality, ModelProfile, reasoning_support

SOURCE = "uncloud"

#: Category to what a model of that category can do. The catalogue's own
#: `capabilities` list refines the image row; everything else is decided here.
_BY_CATEGORY: dict[str, frozenset[Capability]] = {
    "text": frozenset({Capability.TEXT_GENERATE, Capability.CODE_GENERATE}),
    "image": frozenset({Capability.IMAGE_GENERATE}),
    "video": frozenset({Capability.VIDEO_GENERATE, Capability.VIDEO_ANIMATE}),
    "voice-stt": frozenset({Capability.AUDIO_TRANSCRIBE}),
    "voice-tts": frozenset({Capability.AUDIO_SPEAK}),
    "music": frozenset({Capability.AUDIO_GENERATE}),
    #: Not a model you run. A text encoder is a part another model needs, and
    #: saying so is what stops it appearing in a picker as something to choose.
    "component": frozenset({Capability.TEXT_ENCODE}),
}

#: The catalogue's own image vocabulary, which predates the shared one.
_BY_IMAGE_TAG: dict[str, Capability] = {
    "text2img": Capability.IMAGE_GENERATE,
    "edit": Capability.IMAGE_EDIT,
    "reference": Capability.IMAGE_EDIT,
    "inpaint": Capability.IMAGE_INPAINT,
    "upscale": Capability.IMAGE_UPSCALE,
}

_OUTPUTS: dict[str, frozenset[Modality]] = {
    "text": frozenset({Modality.TEXT}),
    "image": frozenset({Modality.IMAGE}),
    "video": frozenset({Modality.VIDEO}),
    "voice-stt": frozenset({Modality.TEXT}),
    "voice-tts": frozenset({Modality.AUDIO}),
    "music": frozenset({Modality.AUDIO}),
    "component": frozenset(),
}


class UnknownCategory(ValueError):
    """A catalogue entry this projection has no mapping for.

    Raised rather than defaulted. A model silently projected as "text" would be
    offered for jobs it cannot do, and the failure would surface as a confusing
    generation error rather than as the missing mapping it actually is.
    """


def capabilities_for(category: str, tags: list[str] | None) -> frozenset[Capability]:
    base = _BY_CATEGORY.get(category)
    if base is None:
        raise UnknownCategory(
            f"No capability mapping for category {category!r}. Add one to "
            f"profiles._BY_CATEGORY rather than letting it default.")
    if category != "image":
        return base
    named = {_BY_IMAGE_TAG[t] for t in (tags or ["text2img"]) if t in _BY_IMAGE_TAG}
    return frozenset(named) or base


def inputs_for(entry_engine: str, capabilities: frozenset[Capability]) -> frozenset[Modality]:
    """What a model can be shown, as opposed to what it produces."""
    inputs = {Modality.TEXT}
    if entry_engine == "mlx-vlm" or Capability.VISION_ANALYSE in capabilities:
        inputs.add(Modality.IMAGE)
    if capabilities & {Capability.IMAGE_EDIT, Capability.IMAGE_INPAINT,
                       Capability.IMAGE_UPSCALE, Capability.VIDEO_ANIMATE}:
        inputs.add(Modality.IMAGE)
    if Capability.AUDIO_TRANSCRIBE in capabilities:
        inputs = {Modality.AUDIO}
    return frozenset(inputs)


def _cost(size_gb: float, category: str) -> Cost:
    """Roughly what this costs resident, from what it costs on disk.

    Deliberately coarse. Uncloud measures the real figure at generation time
    through `budget.resident_weights_gb`, which knows about released encoders
    and per-architecture working sets; this is the cheap estimate used for
    listing and routing, where being within a couple of gigabytes is the whole
    requirement.
    """
    working = {"text": 1.5, "image": 4.0, "video": 6.0}.get(category, 0.5)
    return Cost(weights_gb=size_gb, working_gb=working, download_gb=size_gb)


def from_catalog(entry: CatalogEntry, *, installed: bool = False,
                 runnable: bool | None = None, reason: str = "") -> ModelProfile:
    """One catalogue entry as a profile.

    `runnable` is passed in rather than computed: whether a runtime imports on
    this machine is a live fact the caller already knows, and asking here would
    mean importing torch to list a catalogue.
    """
    from .budget import engine_runs_here

    capabilities = capabilities_for(entry.category, entry.capabilities)
    return ModelProfile(
        id=entry.id,
        name=entry.name,
        source=SOURCE,
        family=entry.id.split("-")[0],
        capabilities=capabilities,
        runtime=entry.engine,
        platforms=("darwin-arm64",) if not engine_runs_here(entry.engine) or
                  entry.engine in ("mflux", "mlx", "mlx-vlm", "text-encoder") else (),
        inputs=inputs_for(entry.engine, capabilities),
        outputs=_OUTPUTS.get(entry.category, frozenset()),
        context_tokens=entry.context_length,
        reasoning=reasoning_support(entry.id, entry.name),
        cost=_cost(entry.size_gb, entry.category),
        #: Empty, and honestly so — see the module docstring. The publisher's
        #: repository is recorded, which is where a person goes to read the
        #: actual terms until this is filled in properly.
        licence=Licence(url=f"https://huggingface.co/{entry.repo}"),
        installed=installed,
        runnable=engine_runs_here(entry.engine) if runnable is None else runnable,
        reason=reason,
        notes=entry.note or "",
    )


def from_local(model, *, runnable: bool | None = None) -> ModelProfile:
    """A model found on disk, which is a weaker claim than a catalogue entry.

    A folder of weights carries no licence and often no provenance. It is
    projected with everything the scanner could establish and nothing it could
    not, which means `UNVERIFIED` terms and no publisher.
    """
    from .budget import engine_runs_here

    capabilities = capabilities_for(model.category, model.capabilities)
    return ModelProfile(
        id=model.id,
        name=model.name,
        source=SOURCE,
        capabilities=capabilities,
        runtime=model.engine,
        inputs=inputs_for(model.engine, capabilities),
        outputs=_OUTPUTS.get(model.category, frozenset()),
        reasoning=reasoning_support(model.id, model.name),
        cost=_cost(model.size_gb, model.category),
        licence=Licence(),
        installed=bool(model.ready),
        runnable=engine_runs_here(model.engine) if runnable is None else runnable,
        notes=model.note or "",
    )


def catalogue_profiles(installed_ids: set[str] | None = None) -> list[ModelProfile]:
    """Every catalogue entry, projected. Cheap: no model is touched."""
    from .catalog import CATALOG

    known = installed_ids or set()
    return [from_catalog(e, installed=e.id in known) for e in CATALOG]


def library_profiles(models_dir) -> list[ModelProfile]:
    """Everything actually on this machine, projected."""
    from .library import scan_library

    return [from_local(m) for m in scan_library(models_dir)]
