"""Describe locked bootstrap archives without downloading or installing them."""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'sidecar' / 'uv.lock'
OUTPUT = ROOT / 'sidecar' / 'setup-manifest.json'


def environment(system: str, machine: str) -> dict:
    return {**default_environment(), 'sys_platform': system, 'platform_machine': machine,
            'platform_system': {'darwin': 'Darwin', 'win32': 'Windows', 'linux': 'Linux'}[system],
            'python_version': '3.12', 'python_full_version': '3.12.13',
            'implementation_version': '3.12.13', 'extra': ''}


def selected_packages(lock: dict, env: dict) -> list[dict]:
    by_name: dict[str, list[dict]] = {}
    for package in lock['package']:
        by_name.setdefault(package['name'], []).append(package)
    pending = [('uncloud-engine', None, ())]
    visited = set()
    selected = {}
    while pending:
        name, version, extras = pending.pop()
        key = (name, version, tuple(extras))
        if key in visited:
            continue
        visited.add(key)
        candidates = [p for p in by_name[name] if not version or p['version'] == version]
        candidates = [p for p in candidates if not p.get('resolution-markers') or any(
            Marker(marker).evaluate(env) for marker in p['resolution-markers'])]
        if len(candidates) != 1:
            raise ValueError(f'Ambiguous locked package: {name} ({env["sys_platform"]})')
        package = candidates[0]
        selected[(name, package['version'])] = package
        dependencies = list(package.get('dependencies', []))
        for extra in extras:
            dependencies.extend(package.get('optional-dependencies', {}).get(extra, []))
        for dependency in dependencies:
            if not dependency.get('marker') or any(Marker(dependency['marker']).evaluate(
                    {**env, 'extra': extra}) for extra in ('', *extras)):
                pending.append((dependency['name'], dependency.get('version'),
                                tuple(dependency.get('extra', []))))
    return [p for p in selected.values() if p['name'] != 'uncloud-engine']


def archive(package: dict, tags: list) -> dict:
    ranked = {tag: index for index, tag in enumerate(tags)}
    choices = []
    for wheel in package.get('wheels', []):
        filename = unquote(urlsplit(wheel['url']).path.rsplit('/', 1)[-1])
        _, _, _, wheel_tags = parse_wheel_filename(filename)
        match = [ranked[tag] for tag in wheel_tags if tag in ranked]
        if match:
            choices.append((min(match), wheel, filename))
    if choices:
        _, item, filename = min(choices, key=lambda row: row[0])
        kind = 'wheel'
    else:
        item = package.get('sdist', {})
        filename = unquote(urlsplit(item.get('url', '')).path.rsplit('/', 1)[-1])
        kind = 'source'
    return {'name': package['name'], 'version': package['version'], 'file': filename,
            'bytes': item.get('size'), 'kind': kind}


def manifest() -> dict:
    raw = LOCK.read_bytes()
    lock = tomllib.loads(raw.decode())
    linux = [f'manylinux_2_{minor}_x86_64' for minor in range(35, 4, -1)]
    linux += ['manylinux2014_x86_64', 'manylinux2010_x86_64', 'manylinux1_x86_64', 'linux_x86_64']
    targets = {'macos-arm64': ('darwin', 'arm64', list(mac_platforms((14, 0), 'arm64'))),
               'windows-x64': ('win32', 'AMD64', ['win_amd64']),
               'linux-x64': ('linux', 'x86_64', linux)}
    profiles = {}
    for target, (system, machine, platforms) in targets.items():
        tags = [*cpython_tags((3, 12), ['cp312'], platforms),
                *compatible_tags((3, 12), 'cp312', platforms)]
        files = sorted((archive(package, tags) for package in selected_packages(
            lock, environment(system, machine))), key=lambda row: row['name'])
        total = sum(row['bytes'] or 0 for row in files)
        profiles[target] = {'download_bytes': total, 'package_count': len(files),
                            'unknown_sizes': sum(row['bytes'] is None for row in files),
                            'source_builds': sum(row['kind'] == 'source' for row in files),
                            'recommended_free_bytes': total * 4 + 2 * 1024**3, 'files': files}
    return {'lock_sha256': hashlib.sha256(raw).hexdigest(), 'profiles': profiles}


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(manifest(), ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'Wrote {OUTPUT.relative_to(ROOT)} from the locked dependency graph.')
