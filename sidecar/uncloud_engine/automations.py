"""Durable, single-flight local agents. No inference on the scheduler's idle path."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .vault import vault

MAGIC = b"UNCLOUD-AUTOMATIONS-1\n"


class NeedsAttention(Exception):
    pass


class Automations:
    def __init__(self, path: Path, execute: Callable[[dict, Callable], Awaitable[dict]], key=None):
        self.path, self.execute = path, execute
        self.key = key or vault.key
        self.items: dict[str, dict] = {}
        self.running: asyncio.Task | None = None
        self.current: str | None = None
        self.loop: asyncio.Task | None = None
        self.error = ""
        if path.exists():
            try:
                raw = path.read_bytes()
                if not raw.startswith(MAGIC):
                    raise ValueError("Unknown automation file format")
                nonce, body = raw[len(MAGIC) : len(MAGIC) + 12], raw[len(MAGIC) + 12 :]
                self.items = json.loads(AESGCM(self.key()).decrypt(nonce, body, MAGIC))
                for item in self.items.values():
                    if item["status"] == "running":
                        item.update(
                            status="needs_attention",
                            paused=True,
                            message="Interrupted by restart. Review progress before resuming.",
                        )
            except Exception:
                self.error = (
                    "Saved agents could not be decrypted. Existing data has not been overwritten."
                )

    def save(self):
        if self.error:
            raise ValueError(self.error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nonce = secrets.token_bytes(12)
        data = (
            MAGIC
            + nonce
            + AESGCM(self.key()).encrypt(nonce, json.dumps(self.items).encode(), MAGIC)
        )
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temp, self.path)

    def create(self, goal, model_path, engine, interval, next_run, tools):
        if interval != 0 and interval < 60:
            raise ValueError("Recurring runs must be at least one minute apart")
        if len(self.items) >= 100:
            raise ValueError("At most 100 saved agents are supported")
        item = dict(
            id=uuid.uuid4().hex,
            goal=goal,
            model_path=model_path,
            engine=engine,
            interval=interval,
            next_run=next_run,
            tools=tools,
            paused=False,
            status="scheduled",
            message="",
            history=[],
            progress=None,
        )
        self.items[item["id"]] = item
        try:
            self.save()
        except Exception:
            self.items.pop(item["id"], None)
            raise
        return item

    def control(self, ident, action):
        item = self.items[ident]
        if action in ("pause", "delete"):
            item["paused"] = True
            if self.current == ident and self.running:
                self.running.cancel()
        if action == "resume":
            if self.current == ident:
                raise ValueError("Wait for the current run to stop")
            item.update(paused=False, status="scheduled", next_run=time.time(), message="")
        elif action == "run":
            if self.current == ident:
                raise ValueError("This agent is already running")
            item.update(
                paused=False, next_run=time.time(), status="scheduled", progress=None, message=""
            )
        elif action == "delete":
            del self.items[ident]
        elif action == "pause":
            item["status"] = "paused"
        elif action != "resume":
            raise ValueError("Unknown action")
        self.save()
        return item

    async def tick(self, now=None):
        if self.error or (self.running and not self.running.done()):
            return
        now = time.time() if now is None else now
        due = sorted(
            (i for i in self.items.values() if not i["paused"] and i["next_run"] <= now),
            key=lambda i: i["next_run"],
        )
        if due:
            self.current = due[0]["id"]
            self.running = asyncio.create_task(self.run(due[0]))
            self.running.add_done_callback(self._finished)

    def _finished(self, task):
        # Cancellation before the coroutine's first instruction never enters its finally.
        if self.running is task:
            self.current = None
        if not task.cancelled() and task.exception() is not None:
            self.error = "The scheduler stopped unexpectedly. Review saved progress."

    async def run(self, item):
        started = time.time()
        item.update(status="running", message="")

        async def update(graph):
            item["progress"] = graph
            self.save()

        try:
            self.save()
            result = await asyncio.wait_for(self.execute(item, update), timeout=600)
            item.update(status="completed", progress=result)
        except asyncio.CancelledError:
            item.update(
                status="paused",
                paused=True,
                message="Stopped. Completed steps are retained; resume replans from this progress.",
            )
        except NeedsAttention as exc:
            item.update(status="needs_attention", paused=True, message=str(exc))
        except Exception as exc:
            item.update(status="failed", paused=True, message=str(exc) or type(exc).__name__)
        finally:
            item["history"].append(
                dict(
                    started=started,
                    ended=time.time(),
                    status=item["status"],
                    message=item["message"],
                    graph=item["progress"],
                )
            )
            item["history"] = item["history"][-20:]
            if item["status"] == "completed":
                item["paused"] = not bool(item["interval"])
                item["next_run"] = time.time() + item["interval"]
                item["progress"] = None
            self.current = None
            try:
                self.save()
            except Exception:
                self.error = (
                    "Saved agents could not be saved. Scheduling has stopped; "
                    "check local storage and encryption."
                )

    async def serve(self):
        while True:
            await self.tick()
            await asyncio.sleep(2)

    async def close(self):
        if self.loop:
            self.loop.cancel()
            await asyncio.gather(self.loop, return_exceptions=True)
        if self.running and not self.running.done():
            self.running.cancel()
            await asyncio.gather(self.running, return_exceptions=True)
