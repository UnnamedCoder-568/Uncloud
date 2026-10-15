"""Explicit user-written personas, separate from ordinary model inference."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from pathlib import Path

from .config import CONFIG_DIR
from .conversations import _decrypt, _encrypt, _write

DIR = CONFIG_DIR / 'personas'


def _path(persona_id: str, owner: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{16}', persona_id):
        raise ValueError('Invalid persona ID.')
    shelf = hashlib.sha256(owner.encode()).hexdigest()
    return DIR / shelf / f'{persona_id}.enc'


def listing(owner: str) -> list[dict]:
    folder = _path('0' * 16, owner).parent
    result = []
    if folder.is_dir():
        for path in folder.glob('*.enc'):
            result.append(_decrypt(path.read_bytes()))
    return sorted(result, key=lambda p: p['updated'], reverse=True)


def save(name: str, instructions: str, model_path: str | None, *, owner: str,
         persona_id: str | None = None) -> dict:
    name, instructions = name.strip(), instructions.strip()
    if not name or len(name) > 120 or not instructions or len(instructions) > 32000:
        raise ValueError('Add a name (up to 120 characters) and persona instructions '
                         '(up to 32,000 characters).')
    now = time.time()
    persona_id = secrets.token_hex(8) if persona_id is None else persona_id
    path = _path(persona_id, owner)
    created = _decrypt(path.read_bytes())['created'] if path.is_file() else now
    record = {'id': persona_id, 'name': name, 'instructions': instructions,
              'model_path': model_path or None, 'created': created, 'updated': now}
    _write(path, _encrypt(record))
    return record
