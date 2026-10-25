"""Durable, private notifications and paused user interactions.

Only trusted engine producers emit events. OS delivery and reading an event
are never authorization. A live waiter, matching owner, pending state and TTL
are required to accept an answer; restart invalidates all old approvals.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .vault import vault

MAGIC = b"UNCLOUD-USER-EVENTS-1\n"

CATEGORIES = {"permission", "question", "completed", "failed", "background", "download", "update"}
TEXT = {
    "permission": ("Chisel needs permission", "Open Uncloud to review the requested action."),
    "question": ("Chisel has a question", "Open Uncloud to continue this task."),
    "completed": ("Task completed", "Your result is ready in Uncloud."),
    "failed": ("Task needs attention", "Open Uncloud to review what happened."),
    "background": ("Background task updated", "Open Uncloud to review its status."),
    "download": ("Model download updated", "Open Models to review the download."),
    "update": ("Uncloud update available", "Open Settings to review the update."),
}
DEFAULTS = {
    "enabled": True,
    "sound": True,
    "system_sound": True,
    "background": True,
    "quiet": False,
    "categories": dict.fromkeys(sorted(CATEGORIES), True),
}
TARGETS = {
    "chat",
    "chisel",
    "automations",
    "models",
    "settings",
    "image",
    "video",
    "music",
    "voice",
}


class EventStore:
    def __init__(self, path: Path, key=None):
        self.path = path
        self.key = key or vault.key
        self.error = ""
        self.lock = threading.RLock()
        self.waiters: dict[str, asyncio.Future] = {}
        try:
            raw = path.read_bytes()
            if raw.startswith(MAGIC):
                nonce, body = raw[len(MAGIC) : len(MAGIC) + 12], raw[len(MAGIC) + 12 :]
                self.data = json.loads(AESGCM(self.key()).decrypt(nonce, body, MAGIC))
            else:
                self.data = json.loads(raw)  # Migrate the development-only JSON format.
        except FileNotFoundError:
            self.data = {}
        except Exception:
            self.data = {}
            self.error = "Notification history could not be decrypted. Existing data is preserved."
        if not isinstance(self.data, dict):
            self.data = {}
        for key, shape in (
            ("events", list),
            ("requests", dict),
            ("runs", dict),
            ("preferences", dict),
            ("inference", dict),
        ):
            if not isinstance(self.data.get(key), shape):
                self.data.pop(key, None)
        self.data.setdefault("events", [])
        self.data.setdefault("requests", {})
        self.data.setdefault("runs", {})
        self.data.setdefault("preferences", copy.deepcopy(DEFAULTS))
        stored_preferences = self.data["preferences"]
        self.data["preferences"] = copy.deepcopy(DEFAULTS)
        for key, value in stored_preferences.items():
            if key != "categories" and key in DEFAULTS and isinstance(value, bool):
                self.data["preferences"][key] = value
        categories = stored_preferences.get("categories", {})
        if isinstance(categories, dict):
            self.data["preferences"]["categories"].update(
                {k: v for k, v in categories.items() if k in CATEGORIES and isinstance(v, bool)}
            )
        self.data["requests"] = {
            k: r
            for k, r in self.data["requests"].items()
            if isinstance(r, dict) and "status" in r and "owner" in r
        }
        self.data["runs"] = {
            k: r
            for k, r in self.data["runs"].items()
            if isinstance(r, dict) and "status" in r and "owner" in r
        }
        self.data["events"] = [
            e
            for e in self.data["events"]
            if isinstance(e, dict)
            and {
                "dedupe",
                "id",
                "owner",
                "category",
                "target",
                "created",
                "read",
                "dismissed",
                "delivery",
            }
            <= e.keys()
        ][-500:]
        # An interrupted action must be reviewed and requested anew. Never
        # treat a disk record or an old notification as a surviving grant.
        for request in self.data["requests"].values():
            if request["status"] == "pending":
                request["status"] = "interrupted"
        for run in self.data["runs"].values():
            if run["status"] in {"planning", "running", "waiting"}:
                run["previous_status"] = run["status"]
                run["status"] = "interrupted"
        if not self.error:
            try:
                self._save()
            except Exception:
                self.error = (
                    "Notification persistence is unavailable. Check local storage and encryption."
                )

    def _save(self):
        if self.error:
            raise ValueError(self.error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        nonce = secrets.token_bytes(12)
        data = (
            MAGIC
            + nonce
            + AESGCM(self.key()).encrypt(
                nonce, json.dumps(self.data, ensure_ascii=False).encode(), MAGIC
            )
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        temp.replace(self.path)

    def preferences(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data["preferences"])

    def set_preferences(self, values: dict) -> dict:
        with self.lock:
            if set(values) - set(DEFAULTS):
                raise ValueError("Unknown notification preference")
            updated = self.preferences()
            for key, value in values.items():
                if key == "categories":
                    if (
                        not isinstance(value, dict)
                        or set(value) - CATEGORIES
                        or any(not isinstance(v, bool) for v in value.values())
                    ):
                        raise ValueError("Invalid notification categories")
                    updated[key].update(value)
                elif not isinstance(value, bool):
                    raise ValueError("Notification preferences must be on or off")
                else:
                    updated[key] = value
            self.data["preferences"] = updated
            self._save()
            return self.preferences()

    def emit(
        self,
        category: str,
        source: str,
        key: str,
        *,
        owner: str = "desktop",
        target: str = "chisel",
        run_id: str = "",
        request_id: str = "",
        conversation_id: str = "",
    ) -> dict:
        if category not in CATEGORIES or target not in TARGETS:
            raise ValueError("Invalid notification category or destination")
        with self.lock:
            dedupe = f"{owner}:{category}:{source}:{key}"
            existing = next((e for e in self.data["events"] if e["dedupe"] == dedupe), None)
            if existing:
                return copy.deepcopy(existing)
            title, body = TEXT[category]  # Never accept prompt/command/model-provided preview text.
            event = {
                "id": uuid.uuid4().hex,
                "category": category,
                "source": source,
                "dedupe": dedupe,
                "owner": owner,
                "title": title,
                "body": body,
                "target": target,
                "run_id": run_id,
                "request_id": request_id,
                "conversation_id": conversation_id,
                "created": time.time(),
                "priority": "attention"
                if category in {"permission", "question", "failed"}
                else "normal",
                "read": False,
                "dismissed": False,
                "delivery": "pending",
            }
            self.data["events"].append(event)
            self.data["events"] = self.data["events"][-500:]
            self._save()
            return copy.deepcopy(event)

    def notify(self, *args, **kwargs):
        """A failed optional completion alert must not fail successful inference."""
        try:
            return self.emit(*args, **kwargs)
        except Exception:
            self.error = (
                "Notification persistence is unavailable. Check local storage and encryption."
            )
            return None

    def listing(self, owner: str) -> dict:
        with self.lock:
            now = time.time()
            events = [
                copy.deepcopy(e)
                for e in reversed(self.data["events"])
                if e["owner"] == owner and not e["dismissed"]
            ]
            requests = [
                copy.deepcopy(r) for r in self.data["requests"].values() if r["owner"] == owner
            ]
            for r in requests:
                if r["status"] == "pending" and r["expires"] <= now:
                    r["status"] = "expired"
            return {
                "events": events,
                "requests": requests,
                "runs": [
                    copy.deepcopy(r)
                    for r in reversed(list(self.data["runs"].values()))
                    if r["owner"] == owner
                ],
                "preferences": self.preferences(),
                "storage_error": self.error,
            }

    def mark(self, owner: str, event_id: str, operation: str):
        if operation not in {"read", "dismiss", "clear", "read_all"}:
            raise ValueError("Unknown notification operation")
        with self.lock:
            found = False
            for e in self.data["events"]:
                if e["owner"] == owner and (
                    operation in {"clear", "read_all"} or e["id"] == event_id
                ):
                    found = True
                    e["read"] = True
                    if operation in {"dismiss", "clear"}:
                        e["dismissed"] = True
            if not found and operation not in {"clear", "read_all"}:
                raise KeyError(event_id)
            if operation == "clear":
                # Clearing history also removes completed private task records.
                # Pending requests remain discoverable until answered/cancelled.
                self.data["requests"] = {
                    key: r
                    for key, r in self.data["requests"].items()
                    if r["owner"] != owner or r["status"] == "pending"
                }
                self.data["runs"] = {
                    key: r
                    for key, r in self.data["runs"].items()
                    if r["owner"] != owner or r["status"] in {"planning", "running", "waiting"}
                }
            self._save()

    def native_batch(self) -> dict:
        """Claim once, before IPC. Avoid duplicates/replay even after a crash."""
        with self.lock:
            preferences = self.preferences()
            eligible = []
            changed = False
            for e in self.data["events"]:
                if e["owner"] != "desktop" or e["delivery"] != "pending":
                    continue
                enabled = preferences["enabled"] and preferences["categories"].get(
                    e["category"], False
                )
                fresh = time.time() - e["created"] < 120 and not e["read"] and not e["dismissed"]
                e["delivery"] = "submitted" if enabled and fresh else "suppressed"
                changed = True
                if enabled and fresh:
                    eligible.append(copy.deepcopy(e))
            if changed:
                self._save()
            return {"events": eligible, "preferences": preferences}

    def delivered(self, event_id: str, status: str):
        if status not in {"submitted", "unavailable", "suppressed"}:
            raise ValueError("Invalid delivery status")
        with self.lock:
            for event in self.data["events"]:
                if event["id"] == event_id and event["owner"] == "desktop":
                    event["delivery"] = status
                    self._save()
                    return
            raise KeyError(event_id)

    def run(
        self, run_id: str, owner: str, status: str, graph: dict | None = None, *, error: str = ""
    ):
        with self.lock:
            existing = self.data["runs"].get(run_id, {})
            if existing and existing["owner"] != owner:
                raise ValueError("Run identifier is already in use")
            self.data["runs"][run_id] = {
                **existing,
                "id": run_id,
                "owner": owner,
                "status": status,
                "updated": time.time(),
                **({"graph": copy.deepcopy(graph)} if graph else {}),
                **({"error": error[:2000]} if error else {}),
            }
            while len(self.data["runs"]) > 30:
                old = next(
                    (
                        key
                        for key, r in self.data["runs"].items()
                        if r["status"] not in {"planning", "running", "waiting"}
                    ),
                    None,
                )
                if old is None:
                    break
                del self.data["runs"][old]
            self._save()

    async def ask(
        self, owner: str, run_id: str, kind: str, details: dict, *, ttl: int = 300, on_offer=None
    ) -> str:
        if kind not in {"permission", "question"}:
            raise ValueError("Unknown interaction type")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        try:
            with self.lock:
                self.waiters[request_id] = future
                self.data["requests"][request_id] = {
                    "id": request_id,
                    "owner": owner,
                    "run_id": run_id,
                    "kind": kind,
                    "details": details,
                    "status": "pending",
                    "created": time.time(),
                    "expires": time.time() + ttl,
                }
                finished = [
                    key for key, r in self.data["requests"].items() if r["status"] != "pending"
                ]
                for key in finished[:-300]:
                    self.data["requests"].pop(key, None)
                self.run(run_id, owner, "waiting")
                self.emit(
                    kind, "chisel", request_id, owner=owner, run_id=run_id, request_id=request_id
                )
            if on_offer:
                await on_offer(request_id)
            return await asyncio.wait_for(future, ttl)
        except TimeoutError:
            with self.lock:
                self.data["requests"][request_id]["status"] = "expired"
            return "expired" if kind == "permission" else ""
        finally:
            with self.lock:
                self.waiters.pop(request_id, None)
                record = self.data["requests"].get(request_id, {})
                if record.get("status") == "pending":
                    record["status"] = "cancelled"
                self._save()

    def answer(self, owner: str, request_id: str, answer: str) -> None:
        with self.lock:
            record = self.data["requests"].get(request_id)
            future = self.waiters.get(request_id)
            run = self.data["runs"].get(record["run_id"], {}) if record else {}
            if not record or record["owner"] != owner:
                raise KeyError(request_id)
            if (
                record["status"] != "pending"
                or record["expires"] <= time.time()
                or not future
                or future.done()
                or run.get("status") != "waiting"
            ):
                raise ValueError(
                    "This request is no longer active. Review the task and run it again."
                )
            valid = {"yes", "no", "always", "never"} if owner == "desktop" else {"yes", "no"}
            if record["kind"] == "permission" and answer not in valid:
                raise ValueError("Unknown permission answer")
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 8000:
                raise ValueError("A response is required (up to 8,000 characters).")
            record["status"] = "answered"
            # Do not persist the answer itself; permission policy is owned by Gate.
            self.run(record["run_id"], owner, "running")
            self._save()
            future.set_result(answer)
