"""Telling somebody a new Uncloud exists, and what else they should know.

Two channels, deliberately separate:

* the APPLICATION update — a signed build that replaces the install — is found
  and installed by the desktop shell through Tauri's updater, which verifies
  the signature before anything runs. Nothing here touches it.
* everything else — announcements, a runtime or model problem worth knowing
  about, a critical notice — comes from a manifest: a JSON file in the public
  repository, which is how a notice reaches every install without a release.
  Pushing one is a commit to `updates/uncloud.json`.

Uncloud's policy is CONTINUOUS: every newer version is offered, majors
included. The manifest is read through Core (`core.updates`), which validates
every field and executes none of them.

Checking is a setting, on by default and shown in Settings. It sends nothing
about this install: the manifest is one static file, the same for everybody,
and the filtering happens here afterwards.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .core import updates

PRODUCT = "uncloud"
POLICY = updates.Policy.CONTINUOUS

#: The announcements manifest. Real and public: a file in the repository this
#: application is built from, so a notice is a commit, not a release.
MANIFEST_URL = ("https://raw.githubusercontent.com/UnnamedCoder-568/Uncloud/"
                "main/updates/uncloud.json")

#: How stale a checked manifest may be before a check happens by itself.
CHECK_EVERY = 6 * 60 * 60


def app_version() -> str:
    """The installed application's version, as the shell reported it.

    From the environment the desktop shell starts the engine with. A checkout
    run by hand falls back to the version in tauri.conf.json beside it, so a
    developer build still compares like the real one.
    """
    reported = os.environ.get("UNCLOUD_APP_VERSION", "").strip()
    if reported:
        return reported
    config = Path(__file__).resolve().parents[2] / "uncloud" / "src-tauri" / "tauri.conf.json"
    try:
        return str(json.loads(config.read_text()).get("version") or "")
    except (OSError, ValueError):
        return ""


class UpdateChecks:
    """The last manifest fetched, what has been dismissed, and when it was checked."""

    def __init__(self, store: Path, *, url: str = MANIFEST_URL,
                 fetch: Callable[[str], object | None] = updates.fetch,
                 version: Callable[[], str] = app_version) -> None:
        self.store = store
        self.url = url
        self._fetch = fetch
        self._version = version
        self._lock = threading.Lock()

    # ----------------------------------------------------------- persistence
    def _load(self) -> dict:
        try:
            data = json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store.with_suffix(".tmp")
        temporary.write_text(json.dumps(data))
        os.replace(temporary, self.store)

    # --------------------------------------------------------------- checking
    def report(self, *, enabled: bool, force: bool = False, version: str = "") -> dict:
        """What this install should be told now, checking first if due."""
        with self._lock:
            data = self._load()
            due = force or time.time() - float(data.get("attempted_at") or 0) > CHECK_EVERY
            if self.url and (enabled or force) and due:
                payload = self._fetch(self.url)
                data["attempted_at"] = time.time()
                if payload is not None:
                    # Kept as fetched; read afresh every time, so a change in
                    # the running version or a dismissal applies at once.
                    data["manifest"] = payload
                    data["checked_at"] = data["attempted_at"]
                self._save(data)

            current = version or self._version()
            report = updates.read(data.get("manifest") or {}, product=PRODUCT,
                                  current_version=current or "0",
                                  dismissed=set(data.get("dismissed") or []), policy=POLICY)
            result = report.to_dict()
            if not data.get("manifest"):
                result["note"] = ("Not checked yet." if not data.get("attempted_at")
                                  else "The update manifest could not be reached.")
            result.update({
                "configured": bool(self.url), "enabled": enabled,
                "checked_at": data.get("checked_at"), "current_version": current,
                "policy": POLICY.value,
            })
            return result

    def dismiss(self, item_id: str) -> None:
        with self._lock:
            data = self._load()
            dismissed = list(data.get("dismissed") or [])
            if item_id not in dismissed:
                dismissed.append(item_id)
            data["dismissed"] = dismissed[-500:]
            self._save(data)
