"""Fetching a model's configuration from Hugging Face — JSON only, on request.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Used only when a person asks for an online lookup, and only for small JSON
files: a scheduler config, a tokenizer config, a pipeline index. Never weights,
and never anything this module did not name itself.

A gated repository is reported as gated. Asking for its files without the
access the publisher requires is exactly the bypass this product does not do —
the person is told to accept the terms on Hugging Face, where they are shown.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

HOST = "https://huggingface.co"
REPO = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[\w.-]{1,96}$")
FILE = re.compile(r"^[\w.-]+(/[\w.-]+)?\.json$")
LIMIT = 4 * 1024 * 1024


class LookupError_(Exception):
    """Base for the ways a lookup fails, each with a sentence for a person."""


class Gated(LookupError_):
    pass


class NotFound(LookupError_):
    pass


class Unreachable(LookupError_):
    pass


def fetch_json(repo: str, file: str, *, token: str | None = None,
               timeout: float = 15.0) -> dict:
    """`file` from the main branch of `repo`, parsed. Raises a LookupError_."""
    if not REPO.match(repo) or ".." in repo:
        raise NotFound(f"'{repo}' is not a Hugging Face repository id.")
    if not FILE.match(file) or ".." in file:
        raise NotFound(f"'{file}' is not a configuration file this looks up.")
    request = urllib.request.Request(
        f"{HOST}/{repo}/resolve/main/{file}",
        headers={"User-Agent": "Uncloud model import"}
        | ({"Authorization": f"Bearer {token}"} if token else {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(LIMIT + 1)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise Gated(f"{repo} is gated. Accept its terms on huggingface.co, then "
                        "add a Hugging Face token in Settings.") from None
        if error.code == 404:
            raise NotFound(f"{repo} has no {file}.") from None
        raise Unreachable(f"Hugging Face answered {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Unreachable("Hugging Face could not be reached.") from None
    if len(body) > LIMIT:
        raise NotFound(f"{file} in {repo} is too large to be a configuration file.")
    try:
        value = json.loads(body)
    except ValueError:
        raise NotFound(f"{file} in {repo} is not valid JSON.") from None
    if not isinstance(value, dict):
        raise NotFound(f"{file} in {repo} is not a JSON object.")
    return value
