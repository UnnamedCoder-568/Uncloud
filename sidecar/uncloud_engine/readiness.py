"""One inventory for first-run setup and every feature's preflight."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .native_chat import install_windows_runtime, server_path

ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()
# id: label, modules, Apple-only, optional environment
SPECS = {
    'chat': ('Local chat', ['llama_cpp.server'], False, None),
    'image': ('Images and editing', ['torch', 'diffusers', 'transformers'], False, None),
    'video': ('Video', ['torch', 'diffusers', 'imageio_ffmpeg'], False, None),
    'transcribe': ('Transcription', ['faster_whisper'], False, None),
    'kokoro': ('Kokoro speech', ['kokoro', 'soundfile'], False, None),
    'bark': ('Bark speech', ['transformers', 'torch', 'soundfile'], False, None),
    'quantize': ('Image quantization', ['mflux', 'mlx.core'], True, None),
    'train': ('Language model training', ['mlx_lm.lora'], True, None),
    'mlx': ('MLX chat and vision', ['mlx_lm', 'mlx_vlm'], True, None),
    'music': ('ACE-Step music', ['acestep.handler'], False, '.venv-acestep'),
    'realtime': ('Realtime narration', ['vibevoice'], False, '.venv-vibevoice'),
    'quality': ('Quality narration', ['vibevoice'], False, '.venv-vibevoice-hq'),
    'chatterbox': ('Chatterbox speech', ['chatterbox'], False, '.venv-chatterbox'),
    'browser': ('Browser tools', ['playwright.sync_api'], False, None),
    'tools': ('Files, web and documents', ['httpx', 'trafilatura'], False, None),
}


def interpreter(env: str | None) -> str:
    if not env:
        return sys.executable
    return str(ROOT / env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))


def check(name: str) -> dict:
    label, modules, apple, env = SPECS[name]
    supported = not apple or (sys.platform == 'darwin' and platform.machine() == 'arm64')
    row = {'id': name, 'label': label, 'supported': supported, 'ready': False, 'detail': ''}
    if not supported:
        row['detail'] = 'Requires an Apple silicon Mac.'
        return row
    native = server_path() if name == 'chat' else None
    if name == 'chat' and (native or sys.platform == 'win32'):
        if native:
            try:
                result = subprocess.run([native, '--version'], capture_output=True,
                                        timeout=30, text=True)
                row['ready'] = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not row['ready']:
            row['detail'] = 'The Windows chat runtime needs installation or repair.'
        return row
    probe = f'import importlib; [importlib.import_module(m) for m in {modules!r}]'
    if name == 'browser':
        probe += ('; from playwright.sync_api import sync_playwright; '
                  'from pathlib import Path; p = sync_playwright().start(); '
                  'assert Path(p.chromium.executable_path).is_file(); p.stop()')
    try:
        result = subprocess.run([interpreter(env), '-c', probe], capture_output=True,
                                text=True, timeout=60)
        row['ready'] = result.returncode == 0
        if not row['ready']:
            row['detail'] = 'Required software is missing or needs repair.'
    except (OSError, subprocess.TimeoutExpired):
        row['detail'] = 'Required software could not start. Install or repair it to continue.'
    return row


def inventory(names: list[str] | None = None) -> list[dict]:
    return [check(name) for name in (names or list(SPECS))]


def _run(args: list[str], say) -> None:
    process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    for line in process.stdout or []:
        say(line.rstrip())
    if process.wait() != 0:
        raise RuntimeError('Installation failed. See the details above and retry.')


def install(name: str, say) -> None:
    if name not in SPECS:
        raise ValueError('Unknown capability')
    if not check(name)['supported']:
        raise ValueError('This capability is not supported on this computer.')
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError('Another installation is running. Wait for it to finish.')
    try:
        uv = os.environ.get('UNCLOUD_UV') or shutil.which('uv')
        if not uv:
            raise RuntimeError('The bundled installer is missing. Reinstall Uncloud.')
        say(f"Installing {SPECS[name][0]}…")
        if name == 'chat' and sys.platform == 'win32':
            install_windows_runtime(say=say)
        elif name == 'music':
            from .music_engine import install_acestep
            install_acestep(say)
        elif name in ('realtime', 'quality'):
            from .narration_engine import install_engine
            install_engine(name, say)
        elif name == 'chatterbox':
            from .speech import install as install_speech
            install_speech(name, say)
        else:
            _run([uv, 'sync', '--locked', '--no-dev'], say)
            if name == 'browser':
                _run([sys.executable, '-m', 'playwright', 'install', 'chromium'], say)
        if not check(name)['ready']:
            raise RuntimeError('Installation finished but verification failed. Retry repair.')
        say('Verified and ready.')
    finally:
        _LOCK.release()
