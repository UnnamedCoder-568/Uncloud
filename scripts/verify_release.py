"""Fail CI when release metadata or bundled runtime files drift apart."""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "uncloud" / "src-tauri"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise SystemExit(f"release verification failed: {message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="", help="tag being released, such as v0.3.0-test.2")
    args = parser.parse_args()

    package = load_json(ROOT / "uncloud" / "package.json")
    package_lock = load_json(ROOT / "uncloud" / "package-lock.json")
    tauri = load_json(TAURI / "tauri.conf.json")
    cargo = tomllib.loads((TAURI / "Cargo.toml").read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads((TAURI / "Cargo.lock").read_text(encoding="utf-8"))
    engine = tomllib.loads((ROOT / "sidecar" / "pyproject.toml").read_text(encoding="utf-8"))
    locked_app = next(item for item in cargo_lock["package"] if item["name"] == "app")

    versions = {
        "package.json": package["version"],
        "package-lock.json": package_lock["version"],
        "package-lock root": package_lock["packages"][""]["version"],
        "tauri.conf.json": tauri["version"],
        "Cargo.toml": cargo["package"]["version"],
        "Cargo.lock": locked_app["version"],
    }
    if len(set(versions.values())) != 1:
        fail("version mismatch: " + ", ".join(f"{name}={value}" for name, value in versions.items()))
    version = next(iter(versions.values()))
    if engine["project"]["version"] != "0.3.0rc2":
        fail("sidecar/pyproject.toml must use the PEP 440 equivalent 0.3.0rc2")
    if args.tag and args.tag != f"v{version}":
        fail(f"tag {args.tag!r} does not match v{version}")

    # The desktop command configures the updater explicitly, while Tauri's
    # packager reads this JSON when creating signed artifacts. Both must trust
    # the same key: leaving the JSON empty builds the whole application and
    # only then fails while signing it.
    public_key = (TAURI / "updater-pubkey.txt").read_text(encoding="utf-8").strip()
    updater = tauri.get("plugins", {}).get("updater", {})
    if updater.get("pubkey") != public_key:
        fail("tauri.conf.json updater pubkey does not match updater-pubkey.txt")
    expected_endpoint = (
        "https://github.com/UnnamedCoder-568/Uncloud/"
        "releases/latest/download/latest.json"
    )
    if updater.get("endpoints") != [expected_endpoint]:
        fail("tauri.conf.json updater endpoint is missing or incorrect")

    resources = tauri["bundle"]["resources"]
    included: set[Path] = set()
    for source in resources:
        pattern = os.path.normpath(os.path.join(TAURI, source))
        included.update(Path(path).resolve() for path in glob.glob(pattern, recursive=True))

    runtime_files = {
        path.resolve()
        for path in (ROOT / "sidecar" / "uncloud_engine").rglob("*")
        if path.is_file() and path.suffix in {".py", ".md", ".json"}
    }
    runtime_files.update(
        (ROOT / "sidecar" / name).resolve()
        for name in ("README.md", "pyproject.toml", "uv.lock")
    )
    runtime_files.update(
        (ROOT / "sidecar" / "scripts" / name).resolve()
        for name in ("acestep_runner.py", "vibevoice_hq_runner.py", "vibevoice_runner.py")
    )
    missing = sorted(runtime_files - included)
    if missing:
        fail("runtime files are not bundled: " + ", ".join(str(path.relative_to(ROOT)) for path in missing))

    expected_platform_resources = {
        "windows": ("binaries/uv.exe", "uv.exe"),
        "linux": ("binaries/uv", "uv"),
        "macos": ("binaries/uv", "uv"),
    }
    for platform, (source, destination) in expected_platform_resources.items():
        config = load_json(TAURI / f"tauri.{platform}.conf.json")
        mapping = config["bundle"]["resources"]
        if mapping.get(source) != destination:
            fail(f"{platform} does not map {source} to {destination}")

    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    for artifact in (
        "Uncloud-Linux-x64.AppImage",
        "Uncloud-macOS-Apple-Silicon.dmg",
    ):
        if artifact not in workflow:
            fail(f"workflow does not name {artifact}")
    # Intel Macs were withdrawn (see README): the engine cannot install there,
    # so the workflow must not build or attach an installer for them.
    if "Uncloud-macOS-Intel.dmg" in workflow:
        fail("workflow still names Uncloud-macOS-Intel.dmg")

    print(f"Release metadata and {len(runtime_files)} runtime files verified for {version}.")


if __name__ == "__main__":
    main()
