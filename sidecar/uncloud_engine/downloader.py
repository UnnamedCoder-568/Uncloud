from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .catalog import CatalogEntry, get_entry
from .config import CONFIG_DIR, settings

HF_RESOLVE = "https://huggingface.co/{repo}/resolve/main/{file}"


@dataclass
class DownloadState:
    id: str
    catalog_id: str
    name: str
    status: str = "pending"  # pending | downloading | done | error | cancelled
    downloaded_bytes: int = 0
    total_bytes: int = 0
    percent: float = 0.0
    speed_bytes_s: float = 0.0
    error: str | None = None
    dest: str = ""
    # Which part is being fetched. A model assembled from several repositories
    # restarts the percentage per file, so without this the bar looks stuck.
    stage: str = ""
    _task: asyncio.Task | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_id": self.catalog_id,
            "name": self.name,
            "status": self.status,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "percent": round(self.percent, 1),
            "speed_bytes_s": round(self.speed_bytes_s, 0),
            "error": self.error,
            "dest": self.dest,
            "stage": self.stage,
        }


def _apply_fixup(fixup: str, dest_dir: Path) -> None:
    """Some community repos don't match the on-disk layout their loader expects.
    Reorganize known-bad layouts here so the model just works after downloading."""
    if fixup == "flat-transformer-shards":
        # mflux expects transformer weights under root/transformer/, but some
        # mflux-community repos ship the shards at the repo root instead.
        index = dest_dir / "model.safetensors.index.json"
        transformer_dir = dest_dir / "transformer"
        if index.exists() and not transformer_dir.exists():
            transformer_dir.mkdir()
            index.rename(transformer_dir / index.name)
            for shard in dest_dir.glob("*.safetensors"):
                shard.rename(transformer_dir / shard.name)


class DownloadManager:
    def __init__(self, state_file: Path | None = None) -> None:
        self.state_file = state_file
        self.downloads: dict[str, DownloadState] = {}
        if state_file and state_file.exists():
            try:
                for item in json.loads(state_file.read_text()):
                    state = DownloadState(**item)
                    if state.status in {"pending", "downloading"}:
                        state.status = "paused"
                    state.speed_bytes_s = 0
                    self.downloads[state.id] = state
            except (OSError, ValueError, TypeError):
                self.downloads = {}

    def _save(self) -> None:
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.list()))
            temporary.replace(self.state_file)

    def list(self) -> list[dict]:
        return [d.to_dict() for d in self.downloads.values()]

    def start(self, catalog_id: str) -> DownloadState:
        entry = get_entry(catalog_id)
        if entry is None:
            raise ValueError(f"Unknown catalog id: {catalog_id}")

        for existing in self.downloads.values():
            if existing.catalog_id == catalog_id and existing.status in {
                "pending",
                "downloading",
                "paused",
            }:
                return existing
        download_id = uuid.uuid4().hex[:12]
        state = DownloadState(
            id=download_id,
            catalog_id=catalog_id,
            name=entry.name,
            dest=str(settings.models_dir / entry.id),
            total_bytes=int(entry.size_gb * 1024**3),
        )
        self.downloads[download_id] = state
        self._save()
        state._task = asyncio.create_task(self._run(state, entry))
        return state

    async def cancel(self, download_id: str) -> None:
        state = self.downloads[download_id]
        if state._task and not state._task.done():
            state._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state._task
        if state.status != "done":
            state.status = "paused"
            state.speed_bytes_s = 0
        self._save()

    def resume(self, download_id: str) -> DownloadState:
        state = self.downloads[download_id]
        if state.status in {"paused", "cancelled", "error"}:
            entry = get_entry(state.catalog_id)
            if entry is None:
                raise ValueError("This model is no longer in the catalog.")
            state.error = None
            state.status = "pending"
            self._save()
            state._task = asyncio.create_task(self._run(state, entry))
        return state

    async def _run(self, state: DownloadState, entry: CatalogEntry) -> None:
        state.status = "downloading"
        try:
            if entry.files:
                dest_dir = Path(state.dest) if state.dest else settings.models_dir / entry.id
                dest_dir.mkdir(parents=True, exist_ok=True)
                state.dest = str(dest_dir)
                for filename in entry.files:
                    await self._download_file(state, entry.repo, filename, dest_dir / filename)
            else:
                dest_dir = Path(state.dest) if state.dest else settings.models_dir / entry.id
                dest_dir.mkdir(parents=True, exist_ok=True)
                state.dest = str(dest_dir)
                await self._download_snapshot(
                    state, entry.repo, dest_dir, entry.allow_patterns or None
                )
            for repo, filename in entry.extra_files:
                state.stage = f"fetching {filename}"
                await self._download_file(state, repo, filename, dest_dir / filename)
            if entry.marker:
                (dest_dir / entry.marker_name).write_text(json.dumps(entry.marker, indent=2) + "\n")
            if entry.fixup:
                _apply_fixup(entry.fixup, dest_dir)
            state.status = "done"
            # A finished download changes what is on disk; without this the
            # new model would not appear until the cache expired.
            from .library import invalidate_library_cache

            for hidden in settings.hidden_models:
                if Path(hidden).is_relative_to(dest_dir):
                    settings.show_model(hidden)
            invalidate_library_cache()
            state.percent = 100.0
        except asyncio.CancelledError:
            state.status = "paused"
            raise
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            state.status = "error"
            state.error = str(exc)
        finally:
            self._save()

    async def _download_file(
        self, state: DownloadState, repo: str, filename: str, dest: Path
    ) -> None:
        if dest.is_file():
            return  # Only completed downloads are renamed to the final filename.
        dest.parent.mkdir(parents=True, exist_ok=True)
        state.stage = filename
        url = HF_RESOLVE.format(repo=repo, file=filename)
        tmp = dest.with_suffix(dest.suffix + ".part")
        resume_from = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

        token = os.environ.get("HF_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        last_tick = time.monotonic()
        last_bytes = resume_from
        state.downloaded_bytes = resume_from

        async with (
            httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(60, connect=20)
            ) as client,
            client.stream("GET", url, headers=headers) as resp,
        ):
            if (
                resp.status_code == 416
                and resp.headers.get("Content-Range") == f"bytes */{resume_from}"
            ):
                tmp.rename(dest)
                state.percent = 100
                return
            resp.raise_for_status()
            # A server may ignore Range. Never append a full response to a partial file.
            if resume_from and resp.status_code != 206:
                resume_from = 0
                state.downloaded_bytes = 0
                last_bytes = 0
            if resp.status_code == 206 and not resp.headers.get("Content-Range", "").startswith(
                f"bytes {resume_from}-"
            ):
                raise RuntimeError(
                    "The server returned an invalid download range. Retry the download."
                )
            content_range_total = resp.headers.get("Content-Length")
            if content_range_total:
                total = int(content_range_total) + resume_from
                if total > 0:
                    state.total_bytes = total

            mode = "ab" if resume_from else "wb"
            with open(tmp, mode) as f:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
                    state.downloaded_bytes += len(chunk)
                    now = time.monotonic()
                    if now - last_tick >= 0.5:
                        state.speed_bytes_s = (state.downloaded_bytes - last_bytes) / (
                            now - last_tick
                        )
                        last_tick, last_bytes = now, state.downloaded_bytes
                        if state.total_bytes:
                            state.percent = min(
                                99.9, state.downloaded_bytes / state.total_bytes * 100
                            )

        tmp.rename(dest)
        state.percent = 100.0

    async def _download_snapshot(
        self,
        state: DownloadState,
        repo: str,
        dest_dir: Path,
        allow_patterns: list[str] | None = None,
    ) -> None:
        # Only metadata runs in a thread. File transfers stay cancellable: cancelling
        # asyncio.to_thread(snapshot_download) used to leave its downloads running.
        from huggingface_hub import HfApi

        files = await asyncio.to_thread(HfApi().list_repo_files, repo_id=repo)
        for filename in files:
            if allow_patterns and not any(
                fnmatch.fnmatch(filename, pattern) for pattern in allow_patterns
            ):
                continue
            target = dest_dir / filename
            if not target.resolve().is_relative_to(dest_dir.resolve()):
                raise ValueError("Invalid repository filename")
            await self._download_file(state, repo, filename, target)


download_manager = DownloadManager(CONFIG_DIR / "downloads.json")
