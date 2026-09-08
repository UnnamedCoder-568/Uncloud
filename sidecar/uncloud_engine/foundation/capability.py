"""The vocabulary Uncloud and Uncloud Studio both speak about models.

THIS FILE IS BYTE-IDENTICAL IN BOTH REPOSITORIES. Verify with md5, not by eye.
If you change it here, copy it there in the same commit; a foundation that has
drifted is worse than none, because it still looks shared.

    Uncloud          sidecar/uncloud_engine/foundation/capability.py
    Uncloud Studio   engine/adstudio_engine/foundation/capability.py

Both products already describe their models, and they describe them
differently. Uncloud's `CatalogEntry` says `category="image"` and
`capabilities=["text2img"]`; Studio's `ModelEntry` says
`capabilities=[Capability.IMAGE_GENERATE]` and adds licence terms, per-variant
platforms and a staged memory estimate. Neither is wrong. They were written for
different jobs and they cannot be compared.

So this is not a third storage format. Nothing here is written to disk and no
catalogue changes shape: a `ModelProfile` is a PROJECTION that each product
builds from whatever it already has, so that routing, effort translation,
feasibility and licence display can be written once against one vocabulary.

Rules this file lives by:

* **Standard library only.** It is copied between two applications with
  different dependency sets; anything else would make the copy conditional.
* **Nothing product-specific.** No paths, no settings, no imports from either
  engine. If a value has to come from the application, it is a field, not a
  lookup.
* **Absence is a value, not a default.** `UNKNOWN` and `None` mean nobody has
  checked. They must never be quietly rendered as a yes — most of the harm this
  vocabulary can do is claiming something is permitted or supported when the
  truth is that nobody looked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: Bumped when a field changes meaning rather than when one is added. Both
#: products assert they agree on it, so a half-copied change is a test failure
#: rather than a subtle disagreement at run time.
VOCABULARY_VERSION = 1


# --------------------------------------------------------------- capability
class Capability(StrEnum):
    """What a model can do. Features bind to capabilities, never to models.

    Dotted and stable: these strings are recorded against jobs, appear in
    permission policy, and are what the orchestrator routes on. Renaming one is
    a user-visible change.
    """

    TEXT_GENERATE = "text.generate"
    #: Reasoning, planning and tool selection. Separate from TEXT_GENERATE
    #: because they want opposite things: writing wants the largest model that
    #: fits, orchestration wants the smallest one that can follow instructions
    #: and stay resident while a specialist takes the machine.
    ORCHESTRATE = "text.orchestrate"
    CODE_GENERATE = "code.generate"
    #: A text encoder is not a model you run; it is a part another model needs.
    TEXT_ENCODE = "text.encode"

    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"
    IMAGE_INPAINT = "image.inpaint"
    IMAGE_UPSCALE = "image.upscale"

    VIDEO_GENERATE = "video.generate"
    VIDEO_ANIMATE = "video.animate"
    #: Video whose motion and timing follow an audio track. A different job
    #: from generating a silent clip and laying sound over it.
    VIDEO_WITH_AUDIO = "video.with_audio"

    #: Music and sound, as opposed to speech.
    AUDIO_GENERATE = "audio.generate"
    AUDIO_SPEAK = "audio.speak"
    AUDIO_TRANSCRIBE = "audio.transcribe"

    VISION_ANALYSE = "vision.analyse"
    EMBED = "embed"


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


# ------------------------------------------------------------------ effort
class ReasoningSupport(StrEnum):
    """How — or whether — a model can be asked to think harder.

    Deliberately a property of the MODEL rather than the runtime. It is the
    chat template that carries it: Qwen3's takes `enable_thinking`, Llama's has
    no such argument, and both are served by the same mlx-lm process. Putting
    it on the runtime would have been tidier and wrong.
    """

    #: Nothing to ask for. Effort has to be spent elsewhere — more passes, a
    #: bigger output budget, a reviewer — and this is the common case.
    NONE = "none"
    #: A boolean on the chat template. Qwen3 and its relatives.
    THINKING_TOGGLE = "toggle"
    #: A token budget for private reasoning.
    BUDGET_TOKENS = "budget"
    #: A named level the provider itself understands.
    EFFORT_LEVEL = "effort"


@dataclass(frozen=True)
class RuntimeProfile:
    """What a runtime accepts, as opposed to what a model can do.

    Transport facts only. Everything here is about the shape of the request the
    runtime will take, which is what effort translation has to work against.
    """

    id: str
    label: str
    #: Platform keys, as `sys.platform`-`machine`. Empty means anywhere.
    platforms: tuple[str, ...] = ()
    accepts_max_tokens: bool = False
    accepts_temperature: bool = False
    #: Whether the runtime implements a structured tool-calling protocol. Text
    #: markers work everywhere and are not counted here — this is specifically
    #: about a protocol the application could rely on instead.
    native_tool_calling: bool = False
    streams: bool = False

    def runs_on(self, platform_key: str) -> bool:
        return not self.platforms or platform_key in self.platforms


APPLE = ("darwin-arm64",)

#: Every runtime either product can drive. Shared so effort translation and
#: feasibility do not each keep their own half-remembered list.
RUNTIMES: dict[str, RuntimeProfile] = {
    r.id: r for r in (
        RuntimeProfile("gguf", "llama.cpp", accepts_max_tokens=True,
                       accepts_temperature=True, streams=True),
        RuntimeProfile("mlx", "MLX", platforms=APPLE, accepts_max_tokens=True,
                       accepts_temperature=True, streams=True),
        RuntimeProfile("mlx-vlm", "MLX vision", platforms=APPLE,
                       accepts_max_tokens=True, accepts_temperature=True,
                       streams=True),
        RuntimeProfile("mflux", "mflux", platforms=APPLE),
        #: An mflux recipe pointing at weights, rather than the weights.
        RuntimeProfile("flux2-profile", "mflux profile", platforms=APPLE),
        #: A checkpoint converted to MLX layout in place.
        RuntimeProfile("mlx-port", "MLX port", platforms=APPLE),
        RuntimeProfile("diffusers", "diffusers"),
        #: A quantised diffusion transformer, which needs the rest of a
        #: pipeline alongside it and is not selectable on its own.
        RuntimeProfile("gguf-diffusion", "GGUF diffusion"),
        RuntimeProfile("faster-whisper", "faster-whisper"),
        RuntimeProfile("kokoro", "Kokoro"),
        RuntimeProfile("vibevoice", "VibeVoice"),
        RuntimeProfile("acestep", "ACE-Step"),
        RuntimeProfile("text-encoder", "Text encoder", platforms=APPLE),
        #: A test double that renders a stub. Never a choice offered to a user.
        RuntimeProfile("fake", "Test double"),
    )
}

#: Stood in for a runtime nobody has described yet.
#:
#: Returned instead of None so a caller asking what a runtime accepts always
#: gets an answer with the right shape. Everything is False, which is the safe
#: direction: a parameter is not sent because the table promised it would be
#: accepted, and the missing entry shows up as a capability that quietly does
#: not work rather than as an exception in unrelated code.
UNKNOWN_RUNTIME = RuntimeProfile("", "Unknown runtime")


def runtime_profile(runtime_id: str) -> RuntimeProfile:
    """What a runtime accepts. Never None — see UNKNOWN_RUNTIME."""
    return RUNTIMES.get(runtime_id, UNKNOWN_RUNTIME)

#: Model families whose chat template accepts a reasoning control, and which.
#: Matched on a lowercase prefix of the family or model id, because a family
#: ships in a dozen sizes and quantisations under a dozen repository names.
#:
#: Measured rather than assumed: a Qwen3 1.7B asked to think spent its entire
#: token budget on an unterminated `<think>` block and produced no answer, and
#: `enable_thinking=False` is what fixed it. Anything not listed here reports
#: NONE, and NONE is the honest answer — effort then has to buy passes rather
#: than depth.
REASONING_FAMILIES: dict[str, ReasoningSupport] = {
    "qwen3": ReasoningSupport.THINKING_TOGGLE,
    "qwq": ReasoningSupport.THINKING_TOGGLE,
    "deepseek-r1": ReasoningSupport.THINKING_TOGGLE,
}


def reasoning_support(*names: str | None) -> ReasoningSupport:
    """The reasoning control this model accepts, from its family or id."""
    for name in names:
        lowered = (name or "").lower()
        for prefix, support in REASONING_FAMILIES.items():
            if prefix in lowered:
                return support
    return ReasoningSupport.NONE


# -------------------------------------------------------------------- cost
@dataclass(frozen=True)
class Cost:
    """What a model needs resident, which is not what it weighs.

    The distinction that decides whether a machine can run something at all is
    between loading everything at once and running the stages in sequence. A
    text-to-video pipeline pairs a very large text encoder with a much smaller
    denoising transformer; the encoder runs once, at the start, and then sits
    there. Encoding, releasing the encoder and only then denoising turns the
    requirement from `encoder + denoiser + working` into
    `max(encoder, denoiser + working)`.
    """

    weights_gb: float = 0.0
    #: Headroom above the weights for activations at typical settings. Weights
    #: alone systematically under-predict and cause a failure at step one.
    working_gb: float = 0.0
    #: The text encoder's share of `weights_gb`. Zero when unknown, or when the
    #: pipeline has no separable encoder.
    encoder_gb: float = 0.0
    #: Whether the runtime can encode, release the encoder, then denoise.
    staged: bool = False
    #: Bytes on disk, which is a different question from bytes in memory.
    download_gb: float = 0.0

    @property
    def total_gb(self) -> float:
        """Everything resident at once — the naive requirement."""
        return self.weights_gb + self.working_gb

    @property
    def peak_gb(self) -> float:
        """The largest amount resident at any one moment."""
        if not (self.staged and self.encoder_gb):
            return self.total_gb
        denoiser = max(0.0, self.weights_gb - self.encoder_gb)
        return max(self.encoder_gb, denoiser + self.working_gb)

    @property
    def saved_by_staging_gb(self) -> float:
        return round(max(0.0, self.total_gb - self.peak_gb), 1)


# ----------------------------------------------------------------- licence
class CommercialUse(StrEnum):
    """What a model's own licence says about commercial use.

    UNVERIFIED is not a synonym for forbidden and not a synonym for allowed. It
    means nobody has read the licence, and it is the honest state for most of
    what a user will install from disk. Rendering it as either answer is the
    single most damaging thing this vocabulary could do.
    """

    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    FORBIDDEN = "forbidden"
    RESEARCH_ONLY = "research_only"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Licence:
    """A third-party model's terms, as recorded — never as inferred.

    Uncloud licenses Uncloud. The publisher licenses the model. Nothing here
    grants, widens or replaces anything: it is a record of what was read, who
    read it and when, so that a user can be told the truth and go and check.

    A summary is a convenience and can be incomplete. `url` is the authority,
    and every surface that shows a classification should offer it.
    """

    #: SPDX identifier where one exists, else the licence's own name.
    id: str = ""
    name: str = ""
    commercial_use: CommercialUse = CommercialUse.UNVERIFIED
    #: May the weights be redistributed — by anyone, including us? Almost
    #: always False, and the reason models are downloaded from source rather
    #: than shipped in an installer.
    redistributable: bool = False
    url: str = ""
    #: Conditions a user must be told about: revenue caps, attribution,
    #: filtering obligations, field-of-use limits.
    conditions: tuple[str, ...] = ()
    #: Who verified these terms and when, so `unverified` is auditable and a
    #: stale reading is visible as one. Publishers relicense.
    verified_by: str = ""
    verified_on: str = ""

    @property
    def verified(self) -> bool:
        return bool(self.verified_on)

    @property
    def needs_disclosure(self) -> bool:
        """Whether a user should be shown the terms before they commit.

        Permissive and verified is the only case that does not: interrupting
        every download would teach people to click through the ones that
        matter.
        """
        return not (self.commercial_use is CommercialUse.ALLOWED and self.verified)


# --------------------------------------------------------------- component
@dataclass(frozen=True)
class Component:
    """One separately-licensed part of a pipeline.

    A generation pipeline is rarely one artefact. A quantised video stack is a
    publisher's skeleton, a transformer from whoever quantised it and a text
    encoder from somebody else again, and those three can carry three different
    licences. Collapsing them into one label produces a confident answer that
    is not true of every part.
    """

    role: str
    name: str
    source: str = ""
    licence: Licence = field(default_factory=Licence)


# ------------------------------------------------------------------ models
@dataclass(frozen=True)
class ModelProfile:
    """One model, described once, in terms both products understand.

    A projection. Each application builds these from its own catalogue and
    nothing is stored in this shape, so adding a field here never migrates
    anything and never invalidates a model already on disk.
    """

    id: str
    name: str
    #: Which application's catalogue this came from, so a combined view can say.
    source: str = ""
    publisher: str = ""
    family: str = ""

    capabilities: frozenset[Capability] = frozenset()
    runtime: str = ""
    #: The specific build: a quantisation, usually.
    variant: str = ""
    platforms: tuple[str, ...] = ()

    inputs: frozenset[Modality] = frozenset({Modality.TEXT})
    outputs: frozenset[Modality] = frozenset()

    context_tokens: int | None = None
    max_output_tokens: int | None = None
    parameters_b: float = 0.0
    reasoning: ReasoningSupport = ReasoningSupport.NONE

    cost: Cost = field(default_factory=Cost)
    licence: Licence = field(default_factory=Licence)
    #: Populated only where a pipeline genuinely has separately-licensed parts.
    components: tuple[Component, ...] = ()

    #: On this machine, now. Resolved by the application, never stored.
    installed: bool = False
    #: Whether a runtime that can execute it is importable here.
    runnable: bool = False
    #: Why not, in the user's terms. Empty when it can run.
    reason: str = ""
    #: A test double rather than a model. Kept so a capability with no runtime
    #: still has a working path, but never offered as a choice.
    placeholder: bool = False
    notes: str = ""

    # -------------------------------------------------------------- queries
    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def sees(self, modality: Modality) -> bool:
        return modality in self.inputs

    @property
    def runtime_profile(self) -> RuntimeProfile:
        return runtime_profile(self.runtime)

    @property
    def runtime_known(self) -> bool:
        """Whether anything has described this runtime.

        False means effort translation and feasibility have nothing to work
        with for it, which is worth surfacing rather than discovering as a
        setting that silently had no effect.
        """
        return self.runtime in RUNTIMES

    @property
    def licences(self) -> tuple[Licence, ...]:
        """Every distinct licence in this model and its components."""
        seen: dict[tuple[str, str], Licence] = {}
        for licence in (self.licence, *(c.licence for c in self.components)):
            if licence.id or licence.name:
                seen.setdefault((licence.id, licence.name), licence)
        return tuple(seen.values())

    @property
    def mixed_licensing(self) -> bool:
        """Whether the parts disagree, which the interface has to say plainly
        rather than picking one of them to display."""
        return len(self.licences) > 1

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "source": self.source,
            "publisher": self.publisher, "family": self.family,
            "capabilities": sorted(c.value for c in self.capabilities),
            "runtime": self.runtime, "variant": self.variant,
            "platforms": list(self.platforms),
            "inputs": sorted(m.value for m in self.inputs),
            "outputs": sorted(m.value for m in self.outputs),
            "context_tokens": self.context_tokens,
            "max_output_tokens": self.max_output_tokens,
            "parameters_b": self.parameters_b,
            "reasoning": self.reasoning.value,
            "cost": {
                "download_gb": round(self.cost.download_gb, 1),
                "weights_gb": round(self.cost.weights_gb, 1),
                "peak_gb": round(self.cost.peak_gb, 1),
                "staged": self.cost.staged,
            },
            "licence": _licence_dict(self.licence),
            "components": [
                {"role": c.role, "name": c.name, "source": c.source,
                 "licence": _licence_dict(c.licence)}
                for c in self.components
            ],
            "mixed_licensing": self.mixed_licensing,
            "installed": self.installed, "runnable": self.runnable,
            "reason": self.reason, "placeholder": self.placeholder,
            "notes": self.notes,
        }


def _licence_dict(licence: Licence) -> dict:
    return {
        "id": licence.id, "name": licence.name,
        "commercial_use": licence.commercial_use.value,
        "redistributable": licence.redistributable,
        "url": licence.url, "conditions": list(licence.conditions),
        "verified_by": licence.verified_by, "verified_on": licence.verified_on,
        "verified": licence.verified,
        "needs_disclosure": licence.needs_disclosure,
    }


# ----------------------------------------------------------------- routing
def with_capability(profiles: list[ModelProfile], capability: Capability,
                    *, installed_only: bool = True) -> list[ModelProfile]:
    """Every model that could serve a capability here, best-fitting last.

    Ordered by cost rather than by quality on purpose: quality is a judgement
    each application makes for itself, and the shared layer has no business
    holding an opinion about it. What it can say is which of them fit.
    """
    found = [p for p in profiles if p.can(capability) and not p.placeholder]
    if installed_only:
        found = [p for p in found if p.installed and p.runnable]
    return sorted(found, key=lambda p: p.cost.peak_gb)


def fits(profile: ModelProfile, budget_gb: float) -> bool:
    """Whether a model fits, using peak rather than total.

    A model that does not fit is not slower. It pages, and generation time
    collapses rather than degrading, so this is a yes or a no and not a score.
    """
    return profile.cost.peak_gb > 0 and profile.cost.peak_gb <= budget_gb
