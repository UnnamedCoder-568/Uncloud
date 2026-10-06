"""Repeat the bounded automated validation without using the owner's app settings.

Run: python3 scripts/stress_check.py --output /private/tmp/uncloud-stress-results.json
Real engine/device scenarios are documented in qa/SCENARIOS.md and are not
silently represented as passed by this runner. No weights are downloaded.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    stages = [('backend', ROOT / 'sidecar', [str(ROOT / 'sidecar/.venv/bin/python'), '-m', 'pytest', 'tests', '-q', '--tb=short']),
              ('frontend', ROOT / 'uncloud', ['npm', 'test']),
              ('production-build', ROOT / 'uncloud', ['npm', 'run', 'build']),
              ('desktop', ROOT / 'uncloud/src-tauri', ['cargo', 'test', '--locked']),
              ('release-metadata', ROOT, ['python3', 'scripts/verify_release.py'])]
    results = []
    with tempfile.TemporaryDirectory(prefix='uncloud-stress-') as config:
        env = dict(os.environ, UNCLOUD_CONFIG_DIR=config)
        for name, cwd, command in stages:
            started = time.monotonic()
            try:
                proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
                result = {'stage': name, 'exit_code': proc.returncode, 'seconds': round(time.monotonic()-started, 3), 'output': proc.stdout + proc.stderr}
            except subprocess.TimeoutExpired:
                result = {'stage': name, 'exit_code': -1, 'seconds': 300, 'output': 'Timed out'}
            results.append(result)
            print(name, 'PASS' if result['exit_code'] == 0 else 'FAIL', flush=True)
    Path(args.output).write_text(json.dumps({'stages': results, 'limits': 'Automated checks only; device and live-generation boundaries are in qa/SCENARIOS.md'}, indent=2))
    raise SystemExit(int(any(r['exit_code'] for r in results)))

if __name__ == '__main__':
    main()
