"""Verified, compiler-free Windows chat runtime shared by packaging and repair."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path

VERSION = 'b11154'
URL = (f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/'
       f'llama-{VERSION}-bin-win-cpu-x64.zip')
SHA256 = '6fe7045523283726cf010203c62d030a3bcc2ac00410e993cd22a5264818f130'
GPU_URL = (f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/'
           f'llama-{VERSION}-bin-win-vulkan-x64.zip')
GPU_SHA256 = 'edbae2fd24cb66e2419f09eb00d0b59a7365e26b449d8313ec498e851f987f05'
RUNTIME_DIR = Path(__file__).resolve().parent.parent / '.llama'


@lru_cache(maxsize=16)
def _inspect(executable: str, stamp: int, size: int) -> dict:
    """Probe the executable, without loading weights or allocating a model cache."""
    result = {'auto_fit': False, 'context_stop': False, 'devices': [], 'template_file': False}
    options = dict(capture_output=True, text=True, timeout=15, check=False,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        help_text = subprocess.run([executable, '--help'], **options)
        text = help_text.stdout + help_text.stderr
        result['auto_fit'] = '--fit-ctx' in text and '--fit ' in text
        result['context_stop'] = '--no-context-shift' in text
        result['template_file'] = '--chat-template-file' in text
        devices = subprocess.run([executable, '--list-devices'], **options)
        if devices.returncode == 0:
            result['devices'] = [match.group(0).strip() for match in re.finditer(
                r'(?m)^\s*(?:Vulkan\d+|CUDA\d+|SYCL\d+|Metal)\s*:\s*[^\n]+',
                devices.stdout + devices.stderr)]
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def inspect_runtime(executable: str | None) -> dict:
    if executable:
        try:
            stat = Path(executable).stat()
            return _inspect(executable, stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
    return {'auto_fit': False, 'context_stop': False, 'devices': [], 'template_file': False}


def host_fit_margin_mb() -> int | None:
    """The native CPU fitter uses total RAM; protect memory already in use."""
    try:
        import psutil

        memory = psutil.virtual_memory()
        return max(1024, (memory.total - memory.available) // (1024 * 1024) + 1024)
    except ImportError:
        pass
    if sys.platform.startswith('linux'):
        try:
            values = dict(re.findall(r'(?m)^(MemTotal|MemAvailable):\s*(\d+) kB',
                                     Path('/proc/meminfo').read_text()))
            return max(1024, (int(values['MemTotal']) - int(values['MemAvailable'])) // 1024
                       + 1024)
        except (OSError, ValueError, KeyError):
            return None
    if sys.platform == 'win32':
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in (
                            'total', 'available', 'page_total', 'page_available',
                            'virtual_total', 'virtual_available', 'extended')]]

        status = Status()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return max(1024, (status.total - status.available) // (1024 * 1024) + 1024)
    return None


def server_path() -> str | None:
    # An explicit publisher/user runtime takes precedence over the bundled fallback.
    explicit = os.environ.get('UNCLOUD_LLAMA_SERVER')
    if explicit and Path(explicit).is_file():
        return explicit
    candidates = []
    if sys.platform == 'win32':
        roots = [RUNTIME_DIR]
        if bundled := os.environ.get('UNCLOUD_LLAMA_RUNTIME_DIR'):
            roots.append(Path(bundled))
        for root in roots:
            gpu = root / 'vulkan' / 'llama-server.exe'
            if gpu.is_file() and inspect_runtime(str(gpu))['devices']:
                return str(gpu)
        for root in roots:
            cpu = root / 'llama-server.exe'
            if cpu.is_file():
                return str(cpu)
    candidates.append(shutil.which('llama-server'))
    return next((p for p in candidates if p and Path(p).is_file()), None)


def _install_archive(url: str, checksum: str, destination: Path) -> None:
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / 'runtime.zip'
        with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as out:
            shutil.copyfileobj(response, out)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('Chat runtime checksum did not match. Please retry.')
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            # Only native runtime executables, libraries and license notices are needed.
            for entry in bundle.infolist():
                name = Path(entry.filename).name
                if not name or entry.is_dir():
                    continue
                if Path(name).suffix.lower() not in {'.exe', '.dll', '.txt', '.md'}:
                    continue
                with bundle.open(entry) as src, (destination / name).open('wb') as dst:
                    shutil.copyfileobj(src, dst)
        if not (destination / 'llama-server.exe').is_file():
            raise RuntimeError('Downloaded runtime does not contain the chat server.')


def install_windows_runtime(destination: Path = RUNTIME_DIR, say=print) -> None:
    say('Downloading the verified Windows CPU and GPU chat runtimes…')
    _install_archive(URL, SHA256, destination)
    _install_archive(GPU_URL, GPU_SHA256, destination / 'vulkan')
    _inspect.cache_clear()
    say('Windows CPU and Vulkan GPU runtimes are installed.')
