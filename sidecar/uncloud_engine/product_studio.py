from __future__ import annotations

from dataclasses import dataclass, field

# Reference-editing models drift away from the source unless you keep telling them
# not to. Every generated instruction ends with a fidelity clause naming the traits
# that actually matter for that product type — listing irrelevant ones ("embroidery"
# on a metal chain) just adds noise the model has to resolve.
_FIDELITY_TRAITS = {
    "apparel": "colour, fabric, weave, print, embroidery, stitching and cut",
    "jewellery": "metal tone, finish, link shape, stones, clasp and proportions",
    "hand": "colour, material, surface finish, markings and proportions",
    "footwear": "colour, material, sole, stitching, hardware and silhouette",
    "object": "colour, material, surface finish, labelling and proportions",
}
_FIDELITY_DEFAULT = "colour, material, markings and proportions"


def fidelity_clause(category_id: str) -> str:
    traits = _FIDELITY_TRAITS.get(category_id, _FIDELITY_DEFAULT)
    return (
        f"Keep the product itself exactly as in the reference image — identical {traits}. "
        "Do not redesign, restyle or embellish the product. Photorealistic commercial "
        "product photography, sharp focus, high detail."
    )


@dataclass
class ShotType:
    id: str
    name: str
    instruction: str
    # Kontext keeps source dimensions when these are None; detail shots want a crop.
    aspect: str = "portrait"  # portrait | square | landscape


@dataclass
class ProductCategory:
    id: str
    name: str
    description: str
    shots: list[ShotType] = field(default_factory=list)
    supports_model: bool = True  # can a human model wear/hold this?


_APPAREL_SHOTS = [
    ShotType("full_front", "Full body — front",
             "Show the full garment worn by a model, standing straight, facing the camera, "
             "full body visible head to toe, clean studio backdrop, soft even lighting."),
    ShotType("three_quarter", "Three-quarter turn",
             "Show the full garment worn by a model turned three-quarters away from the camera, "
             "full body visible, clean studio backdrop, soft even lighting."),
    ShotType("back", "Back view",
             "Show the full garment worn by a model photographed from directly behind, "
             "full body visible, clean studio backdrop, soft even lighting."),
    ShotType("detail", "Detail close-up",
             "Tight close-up on the garment's fabric and embroidery, filling the frame, "
             "showing thread texture and weave at close range, shallow depth of field."),
    ShotType("flat_lay", "Flat lay",
             "Lay the garment flat on a plain neutral surface, photographed straight from above, "
             "neatly arranged, evenly lit, no model.", aspect="square"),
    ShotType("lifestyle", "Lifestyle",
             "Show the garment worn by a model in a natural lifestyle setting with soft "
             "natural daylight and a softly blurred background."),
]

_JEWELLERY_SHOTS = [
    ShotType("on_model", "On model",
             "Show the piece worn by a model, framed on the neckline and collarbone, "
             "clean studio backdrop, soft directional lighting that flatters the metal."),
    ShotType("macro", "Macro detail",
             "Extreme macro close-up of the piece filling the frame, showing link shape, "
             "clasp and surface finish, crisp reflections, shallow depth of "
             "field.", aspect="square"),
    ShotType("flat_lay", "Flat lay",
             "Arrange the piece on a plain neutral surface photographed from directly above, "
             "gently coiled, evenly lit, no model.", aspect="square"),
    ShotType("in_hand", "Held in hand",
             "Show the piece held between the fingers of a well-groomed hand, "
             "clean background, soft lighting.", aspect="square"),
]

_HAND_SHOTS = [
    ShotType("held", "Held in hand",
             "Show the product held naturally in a well-groomed hand, clean studio backdrop, "
             "soft lighting, hand posed to show the product clearly.", aspect="square"),
    ShotType("in_use", "In use",
             "Show the product being used naturally by a pair of well-groomed hands, "
             "clean background, soft lighting."),
    ShotType("macro", "Macro detail",
             "Extreme close-up of the product against the skin of the hand, showing surface "
             "texture and finish, shallow depth of field.", aspect="square"),
]

_FOOTWEAR_SHOTS = [
    ShotType("on_foot", "Worn — side profile",
             "Show the footwear worn, photographed from the side at ground level, "
             "clean studio backdrop, soft even lighting."),
    ShotType("on_foot_front", "Worn — front",
             "Show the footwear worn, photographed from the front at ground level, "
             "clean studio backdrop, soft even lighting."),
    ShotType("walking", "In motion",
             "Show the footwear worn mid-stride in a natural outdoor setting, "
             "soft natural daylight, softly blurred background."),
    ShotType("flat_lay", "Flat lay",
             "Arrange the footwear on a plain neutral surface photographed from above, "
             "evenly lit, no model.", aspect="square"),
    ShotType("detail", "Detail close-up",
             "Tight close-up on the footwear's material and stitching, filling the frame, "
             "shallow depth of field.", aspect="square"),
]

_OBJECT_SHOTS = [
    ShotType("studio", "Studio hero",
             "Show the product centred on a clean seamless studio backdrop, "
             "soft even lighting, subtle contact shadow, no model.", aspect="square"),
    ShotType("angle", "Three-quarter angle",
             "Show the product at a three-quarter angle on a clean studio surface, "
             "soft lighting, subtle reflection.", aspect="square"),
    ShotType("detail", "Macro detail",
             "Extreme macro close-up of the product's surface, texture and finish, "
             "shallow depth of field.", aspect="square"),
    ShotType("lifestyle", "Lifestyle",
             "Show the product in a natural lifestyle setting with soft daylight and "
             "a softly blurred background."),
]

CATEGORIES: list[ProductCategory] = [
    ProductCategory("apparel", "Apparel & Textile",
                    "Kurtas, dresses, shirts — anything worn on the body.", _APPAREL_SHOTS),
    ProductCategory("jewellery", "Jewellery & Chains",
                    "Chains, necklaces, rings, earrings.", _JEWELLERY_SHOTS),
    ProductCategory("hand", "Hand Modelling",
                    "Products presented in or by the hands.", _HAND_SHOTS),
    ProductCategory("footwear", "Footwear & Feet",
                    "Shoes, sandals, socks, hosiery.", _FOOTWEAR_SHOTS),
    ProductCategory("object", "Product / Object",
                    "Bags, watches, cosmetics, packaged goods.", _OBJECT_SHOTS,
                    supports_model=False),
]

ASPECT_SIZES = {
    "portrait": (768, 1024),
    "square": (1024, 1024),
    "landscape": (1024, 768),
}


def get_categories() -> list[ProductCategory]:
    return CATEGORIES


def get_category(category_id: str) -> ProductCategory | None:
    return next((c for c in CATEGORIES if c.id == category_id), None)


def get_shot(category_id: str, shot_id: str) -> ShotType | None:
    cat = get_category(category_id)
    if not cat:
        return None
    return next((s for s in cat.shots if s.id == shot_id), None)


def build_instruction(
    category_id: str, shot_id: str, *,
    model_description: str = "",
    background: str = "",
    extra: str = "",
) -> str:
    """Compose the full Kontext instruction for one product shot."""
    shot = get_shot(category_id, shot_id)
    if shot is None:
        raise ValueError(f"Unknown shot '{shot_id}' for category '{category_id}'")

    parts = [shot.instruction]
    cat = get_category(category_id)
    if model_description and cat and cat.supports_model:
        parts.append(f"The model is {model_description}.")
    if background:
        parts.append(f"Background: {background}.")
    if extra:
        parts.append(extra)
    parts.append(fidelity_clause(category_id))
    return " ".join(p.strip() for p in parts if p.strip())


def to_dict() -> list[dict]:
    return [
        {
            "id": c.id, "name": c.name, "description": c.description,
            "supports_model": c.supports_model,
            "shots": [
                {"id": s.id, "name": s.name, "aspect": s.aspect} for s in c.shots
            ],
        }
        for c in CATEGORIES
    ]
