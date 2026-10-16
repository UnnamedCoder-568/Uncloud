import importlib.util
import json
from pathlib import Path

from packaging.tags import Tag

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('setup_manifest', ROOT / 'scripts/setup_manifest.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_platform_dependencies_and_requested_extras_exclude_unrelated_archives():
    lock = {'package': [
        {'name': 'uncloud-engine', 'version': '1', 'dependencies': [
            {'name': 'shared', 'extra': ['server']},
            {'name': 'apple-only', 'marker': "sys_platform == 'darwin'"}]},
        {'name': 'shared', 'version': '1', 'optional-dependencies': {
            'server': [{'name': 'server'}], 'unused': [{'name': 'unused'}]}},
        *({'name': name, 'version': '1'} for name in ('apple-only', 'server', 'unused')),
    ]}
    names = {p['name'] for p in setup.selected_packages(lock, setup.environment('win32', 'AMD64'))}
    assert names == {'shared', 'server'}
    names = {p['name'] for p in setup.selected_packages(lock, setup.environment('darwin', 'arm64'))}
    assert names == {'shared', 'server', 'apple-only'}


def test_archive_selection_keeps_unknown_sizes_unknown_and_rejects_other_platform_wheels():
    package = {'name': 'sample', 'version': '1', 'wheels': [
        {'url': 'https://example.org/sample-1-cp312-cp312-win_amd64.whl', 'size': 100},
        {'url': 'https://example.org/sample-1-py3-none-any.whl'},
    ]}
    result = setup.archive(package, [Tag('py3', 'none', 'any')])
    assert result['file'] == 'sample-1-py3-none-any.whl'
    assert result['bytes'] is None


def test_shipped_manifest_matches_the_current_locked_graph_and_archive_metadata():
    assert json.loads(setup.OUTPUT.read_text()) == setup.manifest()
