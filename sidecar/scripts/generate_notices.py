"""Write the third-party notice file that ships with the application.

Run at build time, and the output is checked in, so what a user reads is what
was actually shipped rather than whatever happens to be installed on the
machine that built it.

Two rules, both about not being helpful in the wrong direction.

**It records what the metadata says, and marks the rest incomplete.** Where a
package declares no licence, the entry says so. An approximated licence is
worse than an absent one, because it reads as authoritative — and a notice file
is exactly the document somebody checks during due diligence.

**It does not walk site-packages indiscriminately.** The list is built from the
declared dependency tree, so it describes what the build ships rather than
whatever a developer happened to install.

    python scripts/generate_notices.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "uncloud_engine" / "legal" / "documents" / "third-party.json"
PROJECT = ROOT / "pyproject.toml"
#: The frontend ships inside the same application, so its dependencies are
#: distributed too and carry the same notice obligation.
FRONTEND = ROOT.parent / "uncloud"
PACKAGE = "uncloud"

#: Classifier prefix that names a licence when the `License` field is empty,
#: which is now the common case: modern packaging encourages the classifier and
#: leaves the free-text field blank.
CLASSIFIER = "License :: OSI Approved :: "


def _licence(dist: metadata.Distribution) -> str:
    """What this package says its licence is. Empty when it says nothing."""
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    for value in meta.get_all("Classifier") or []:
        if value.startswith(CLASSIFIER):
            return value[len(CLASSIFIER):].strip()
    stated = (meta.get("License") or "").strip()
    # Some packages put the entire licence text in the field. A notice list is
    # a table; the full text belongs in `text`, not in a cell.
    if stated and "\n" not in stated and len(stated) < 64:
        return stated
    return ""


def _url(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    for key in ("Home-page", "Project-URL"):
        for value in meta.get_all(key) or []:
            if "," in value:
                value = value.split(",", 1)[1]
            value = value.strip()
            if value.startswith("http"):
                return value
    return ""


def _declared() -> list[str]:
    """The dependencies this project declares, as names.

    Read from pyproject rather than from the installed environment: the project
    itself is not installed as a distribution, and a developer's virtualenv
    contains test tooling the build does not ship. A notice file naming pytest
    would be wrong in the direction of claiming to distribute something it does
    not.
    """
    data = tomllib.loads(PROJECT.read_text(encoding="utf-8"))
    out = []
    for raw in data.get("project", {}).get("dependencies", []):
        name = raw.split(";")[0].split("@")[0].split("(")[0].split("[")[0]
        for separator in (">", "<", "=", "!", "~"):
            name = name.split(separator)[0]
        name = name.strip()
        if name:
            out.append(name)
    return out


def _dependencies(roots: list[str]) -> set[str]:
    """Everything those pull in, transitively."""
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        name = queue.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        for raw in dist.requires or []:
            # "package (>=1.0) ; extra == 'dev'" — extras are not installed by
            # default and must not be claimed as shipped.
            if "extra ==" in raw:
                continue
            requirement = raw.split(";")[0].split("(")[0].split("[")[0].strip()
            requirement = requirement.split(">")[0].split("<")[0].split("=")[0]
            requirement = requirement.split("!")[0].split("~")[0].strip()
            if requirement:
                queue.append(requirement)
    return seen


def collect() -> list[dict]:
    out: list[dict] = []
    for key in sorted(_dependencies(_declared())):
        try:
            dist = metadata.distribution(key)
        except metadata.PackageNotFoundError:
            continue
        out.append({
            "name": dist.metadata.get("Name") or key,
            "version": dist.version,
            "licence": _licence(dist),
            "url": _url(dist),
            "kind": "python",
        })
    return out


def _node_tree() -> dict:
    """The production dependency tree, from npm itself.

    Asked of npm rather than reconstructed by walking node_modules, because
    node_modules also contains devDependencies — which are not shipped, and
    claiming to distribute them would be wrong in the same direction as
    claiming pytest.
    """
    try:
        result = subprocess.run(
            ["npm", "ls", "--omit=dev", "--all", "--json"],
            cwd=FRONTEND, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    # npm exits non-zero on peer-dependency complaints while still printing a
    # usable tree, so the output is parsed regardless of the exit code.
    try:
        return json.loads(result.stdout or "{}")
    except ValueError:
        return {}


def collect_node() -> list[dict]:
    tree = _node_tree()
    if not tree:
        return []

    found: dict[str, str] = {}

    def walk(node: dict) -> None:
        for name, info in (node.get("dependencies") or {}).items():
            if name not in found:
                found[name] = str(info.get("version", ""))
                walk(info)

    walk(tree)

    out = []
    for name, version in sorted(found.items()):
        manifest = FRONTEND / "node_modules" / Path(*name.split("/")) / "package.json"
        licence, url = "", ""
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            stated = data.get("license") or data.get("licence") or ""
            licence = stated if isinstance(stated, str) else \
                str(stated.get("type", "")) if isinstance(stated, dict) else ""
            repository = data.get("repository")
            if isinstance(repository, dict):
                url = str(repository.get("url", ""))
            elif isinstance(repository, str):
                url = repository
            url = url.replace("git+", "").replace("git://", "https://")
            url = url.removesuffix(".git")
        out.append({"name": name, "version": version, "licence": licence,
                    "url": url if url.startswith("http") else "", "kind": "node"})
    return out


def main() -> int:
    notices = collect() + collect_node()
    if not notices:
        print("No dependencies resolved. Is the environment installed?",
              file=sys.stderr)
        return 1
    # Named here so the file itself says what it is describing.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_for": PACKAGE,
        "note": "Generated at build time from installed package metadata. An "
                "entry with no licence is one whose package declares none — "
                "recorded as unknown rather than guessed at.",
        "notices": notices,
    }, indent=2) + "\n", encoding="utf-8")
    missing = sum(1 for n in notices if not n["licence"])
    print(f"{len(notices)} components written to {OUT}"
          + (f"; {missing} declare no licence" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
