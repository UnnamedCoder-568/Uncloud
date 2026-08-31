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
        return bool(self._data.get("onboarded", False))

    def mark_onboarded(self) -> None:
        self._data["onboarded"] = True
        self._save()

    @property
    def agent_device_access(self) -> bool:
        """Whether Agent Mode may run shell commands / touch the full filesystem.

        Defaults to False (workspace-scoped only); the user opts in explicitly
        in Settings before the agent gets a real shell.
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
