"""Verified, compiler-free Windows chat runtime shared by packaging and repair."""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = 'b11154'
URL = (f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/'
       f'llama-{VERSION}-bin-win-cpu-x64.zip')
SHA256 = '6fe7045523283726cf010203c62d030a3bcc2ac00410e993cd22a5264818f130'
RUNTIME_DIR = Path(__file__).resolve().parent.parent / '.llama'


def server_path() -> str | None:
    candidates = []
    if sys.platform == 'win32':
        candidates.append(str(RUNTIME_DIR / 'llama-server.exe'))
    candidates.extend([os.environ.get('UNCLOUD_LLAMA_SERVER'), shutil.which('llama-server')])
    return next((p for p in candidates if p and Path(p).is_file()), None)


def install_windows_runtime(destination: Path = RUNTIME_DIR, say=print) -> None:
    say('Downloading the verified Windows chat runtime…')
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / 'runtime.zip'
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open('wb') as out:
            shutil.copyfileobj(response, out)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
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
    say('Windows chat runtime is installed.')
