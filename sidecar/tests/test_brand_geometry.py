"""The mark is drawn twice, and the two drawings must agree.

The interface draws the cloud in SVG so it stays crisp and takes the theme's
accent; the icon generator draws the same cloud in pixels because an app icon
is 1024 across and the supplied artwork is 141. Two drawings of one mark is a
real risk — nudge the shoulders in the component and the icon silently stops
matching the application it belongs to.

So the numbers are compared across the language boundary. There is no clever
sharing here on purpose: a build step that generated one from the other would
be more machinery than a mark that changes once a year deserves.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "uncloud" / "src" / "components" / "Wordmark.tsx"
GENERATOR = ROOT / "uncloud" / "scripts" / "make_icons.py"

FIELDS = ("w", "h", "r1", "cy1", "rl", "yl", "rb", "top")


def _from_tsx(name: str) -> dict[str, float]:
    """Read `const NAME: Cloud = { ... }` out of the component."""
    text = COMPONENT.read_text()
    match = re.search(rf"const {name}: Cloud = \{{(.*?)\}};", text, re.S)
    assert match, f"{name} is not defined in {COMPONENT.name}"
    return {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)", match.group(1))}


def _from_python(name: str) -> dict[str, float]:
    """Read `NAME = dict(...)` out of the generator."""
    text = GENERATOR.read_text()
    match = re.search(rf"^{name} = dict\((.*?)\)$", text, re.S | re.M)
    assert match, f"{name} is not defined in {GENERATOR.name}"
    return {k: float(v) for k, v in re.findall(r"(\w+)=(-?[\d.]+)", match.group(1))}


def test_the_outer_cloud_is_the_same_in_both() -> None:
    tsx, py = _from_tsx("OUTER"), _from_python("OUTER")
    for field in FIELDS:
        assert tsx[field] == py[field], (
            f"OUTER.{field} is {tsx[field]} in the interface and {py[field]} in "
            f"the icon generator — the app icon no longer matches the app")


def test_the_inner_cloud_is_the_same_in_both() -> None:
    tsx, py = _from_tsx("INNER"), _from_python("INNER")
    for field in FIELDS:
        assert tsx[field] == py[field], (
            f"INNER.{field} is {tsx[field]} in the interface and {py[field]} in "
            f"the icon generator")


def test_the_knockout_sits_in_the_same_place() -> None:
    text = COMPONENT.read_text()
    match = re.search(r"const INNER_AT = \{ x: ([\d.]+), y: ([\d.]+) \};", text)
    assert match, "INNER_AT is not defined in the component"
    ours = (float(match.group(1)), float(match.group(2)))

    generator = GENERATOR.read_text()
    other = re.search(r"INNER_AT = \(([\d.]+), ([\d.]+)\)", generator)
    assert other, "INNER_AT is not defined in the generator"
    assert ours == (float(other.group(1)), float(other.group(2)))


def test_every_icon_the_bundle_asks_for_exists() -> None:
    """A missing icon does not fail the build; it ships an app with no icon."""
    import json

    conf = json.loads(
        (ROOT / "uncloud" / "src-tauri" / "tauri.conf.json").read_text())
    missing = [name for name in conf["bundle"]["icon"]
               if not (ROOT / "uncloud" / "src-tauri" / name).is_file()]
    assert not missing, f"these icons are listed but absent: {missing}"
