from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

CONFIG_DIR = Path.home() / ".uncloud"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Only used until onboarding asks where models should live; must not assume
# anything about this particular machine.
DEFAULT_MODELS_DIR = str(Path.home() / "Uncloud" / "models")


class Settings:
    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._data = self._load()
        # Auth token for the sidecar HTTP/WS API. Generated fresh per app launch
        # unless pinned via env (Tauri passes it in when it spawns us).
        self.token = os.environ.get("UNCLOUD_TOKEN") or secrets.token_hex(24)
        if self._data.get("hf_token"):
            os.environ["HF_TOKEN"] = self._data["hf_token"]

    def _load(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        CONFIG_FILE.write_text(json.dumps(self._data, indent=2))

    @property
    def models_dir(self) -> Path:
        path = self._data.get("models_dir") or DEFAULT_MODELS_DIR
        return Path(path)

    def set_models_dir(self, path: str) -> None:
        self._data["models_dir"] = path
        Path(path).mkdir(parents=True, exist_ok=True)
        self._save()

    @property
    def onboarded(self) -> bool:
        return bool(self._data.get("onboarded", False) and self._data.get("models_dir"))

    def mark_onboarded(self) -> None:
        self._data["onboarded"] = True
        self._save()

    @property
    def agent_device_access(self) -> bool:
        """How far outside the workspace file tools may reach.

        A SCOPE, not a permission, and the two are now separate things. This
        decides which paths `_resolve_path` will resolve; the approval policy
        decides whether a write happens at all. Both apply, and neither
        substitutes for the other.

        It was never the sandbox its name suggests. With it off, the `fs_*`
        tools are confined and `_shell` gets the workspace as its working
        directory — but the command itself was always unrestricted, so
        `cd ~ && …` ran. That hole is closed by shell being its own approval
        category that asks every time and cannot be granted for a session, not
        by this flag.
        """
        return bool(self._data.get("agent_device_access", False))

    def set_agent_device_access(self, enabled: bool) -> None:
        self._data["agent_device_access"] = enabled
        self._save()

    @property
    def agent_tool_groups(self) -> list[str] | None:
        """Which tool groups the agent's planner may see.

        None means choose automatically from the loaded model's size — a small
        model plans better against ten tools than thirty-one.
        """
        v = self._data.get("agent_tool_groups")
        return list(v) if isinstance(v, list) else None

    def set_agent_tool_groups(self, groups: list[str] | None) -> None:
        if groups is None:
            self._data.pop("agent_tool_groups", None)
        else:
            self._data["agent_tool_groups"] = list(groups)
        self._save()

    @property
    def effort(self) -> str:
        """How hard to think, by default. Balanced until somebody says else."""
        return str(self._data.get("effort") or "balanced")

    def set_effort(self, level: str) -> None:
        self._data["effort"] = level
        self._save()

    # ------------------------------------------------------------ approvals
    @property
    def permission_policy(self) -> dict:
        """What the user has decided about each category of action.

        Stored as plain strings so an unreadable value degrades to the default
        rather than to permission — `foundation.load_policy` drops anything it
        does not recognise, and the defaults are the strict ones.
        """
        raw = self._data.get("permission_policy")
        return dict(raw) if isinstance(raw, dict) else {}

    def set_permission_policy(self, policy: dict) -> None:
        self._data["permission_policy"] = dict(policy)
        self._save()

    # ---------------------------------------------------------------- legal
    # Terms live beside the other settings rather than in a database, because
    # Uncloud has no application database and adding one to hold three rows
    # would be a second place for state to be. Kept SEPARATE from
    # `permission_policy` above with a comment saying so, because these two
    # dictionaries are the exact pair that must never be confused: one records
    # what a person agreed to, the other what an agent may do.
    @property
    def terms_acceptances(self) -> list[dict]:
        raw = self._data.get("terms_acceptances")
        return [dict(r) for r in raw] if isinstance(raw, list) else []

    def record_acceptance(self, acceptance: dict) -> None:
        """Store agreement to one document, keeping the highest version.

        Downgrading the application must not withdraw consent already given to
        a later version.
        """
        kept = [a for a in self.terms_acceptances
                if a.get("document_id") != acceptance.get("document_id")
                or int(a.get("version", 0)) > int(acceptance.get("version", 0))]
        if all(a.get("document_id") != acceptance.get("document_id")
               for a in kept):
            kept.append(dict(acceptance))
        self._data["terms_acceptances"] = kept
        self._save()

    @property
    def licence_acknowledgements(self) -> dict:
        """That a model's terms were SHOWN. Not a grant, and never consulted to
        decide whether anything may run."""
        raw = self._data.get("licence_acknowledgements")
        return dict(raw) if isinstance(raw, dict) else {}

    def record_acknowledgement(self, model_id: str, entry: dict) -> None:
        existing = self.licence_acknowledgements
        existing[model_id] = dict(entry)
        self._data["licence_acknowledgements"] = existing
        self._save()

    @property
    def output_dir(self) -> Path:
        """Where generated work is written.

        Defaults inside the config folder only because something has to work
        before the user has chosen; a dotfolder is a bad home for images and
        audio a person will want to open, send and keep, so this is meant to be
        pointed somewhere real.
        """
        path = self._data.get("output_dir")
        return Path(path) if path else CONFIG_DIR / "outputs"

    def set_output_dir(self, path: str) -> None:
        self._data["output_dir"] = path
        Path(path).mkdir(parents=True, exist_ok=True)
        self._save()

    @property
    def output_dir_is_default(self) -> bool:
        return not self._data.get("output_dir")

    @property
    def check_updates(self) -> bool:
        """Whether Uncloud looks for new versions and notices by itself.

        On by default, and a setting rather than something assumed: checking
        is a request to GitHub, and a local-first product says so. It sends
        nothing about this install — see update_checks.py.
        """
        return bool(self._data.get("check_updates", True))

    def set_check_updates(self, enabled: bool) -> None:
        self._data["check_updates"] = bool(enabled)
        self._save()

    @property
    def keep_awake(self) -> bool:
        """Whether to stop the machine sleeping while a job runs.

        Off by default: holding a wake lock is the kind of thing an app should
        ask for rather than assume, and short jobs do not need it.
        """
        return bool(self._data.get("keep_awake", False))

    def set_keep_awake(self, enabled: bool) -> None:
        self._data["keep_awake"] = enabled
        self._save()

    @property
    def imported_models(self) -> list[str]:
        """Models added from outside the models folder, by path.

        Kept as paths and nothing else: what each one is gets re-read from its
        files every scan, so a model changed on disk is never described by a
        stale record here.
        """
        return [str(p) for p in self._data.get("imported_models") or []]

    def remember_imported(self, path: str) -> None:
        known = self.imported_models
        if path not in known:
            self._data["imported_models"] = [*known, path]
            self._save()

    def forget_imported(self, path: str) -> bool:
        known = self.imported_models
        if path not in known:
            return False
        self._data["imported_models"] = [p for p in known if p != path]
        self._save()
        return True

    @property
    def hf_token_set(self) -> bool:
        return bool(self._data.get("hf_token"))

    def set_hf_token(self, token: str) -> None:
        token = token.strip()
        if token:
            self._data["hf_token"] = token
            os.environ["HF_TOKEN"] = token
        else:
            self._data.pop("hf_token", None)
            os.environ.pop("HF_TOKEN", None)
        self._save()


settings = Settings()


def output_dir_for(kind: str = "") -> Path:
    """Resolve the output folder at call time.

    Read live rather than captured at import, so changing the folder in
    Settings takes effect without restarting the engine.
    """
    base = settings.output_dir
    target = base / kind if kind else base
    target.mkdir(parents=True, exist_ok=True)
    return target
