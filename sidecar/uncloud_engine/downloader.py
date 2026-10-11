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

HF_RESOLVE = "https://huggingface.co/{repo}/resolve/{revision}/{file}"


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
    # A pinned manifest keeps progress cumulative and resumes the same revision.
    stage: str = ""
    files: list[dict] = field(default_factory=list)
    completed_files: int = 0
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
            "files": self.files,
            "completed_files": self.completed_files,
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
        self.on_finished = None
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
            if (existing.catalog_id == catalog_id and existing.status == "done"
                    and self._complete_on_disk(existing, entry)):
                for hidden in settings.hidden_models:
                    if Path(hidden).is_relative_to(Path(existing.dest)):
                        settings.show_model(hidden)
                from .library import invalidate_library_cache

                invalidate_library_cache()
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

    @staticmethod
    def _complete_on_disk(state: DownloadState, entry: CatalogEntry) -> bool:
        if not state.files:
            return False  # Older records have no verifiable manifest.
        for item in state.files:
            target = Path(state.dest) / item["filename"]
            if not target.is_file() and entry.fixup == "flat-transformer-shards":
                target = Path(state.dest) / "transformer" / item["filename"]
            if not target.is_file() or target.stat().st_size != item["size"]:
                return False
        return True

    async def _run(self, state: DownloadState, entry: CatalogEntry) -> None:
        state.status = "downloading"
        try:
            dest_dir = Path(state.dest) if state.dest else settings.models_dir / entry.id
            dest_dir.mkdir(parents=True, exist_ok=True)
            state.dest = str(dest_dir)
            self._mark_folder(dest_dir, "downloading")
            state.stage = "Preparing download"
            if not state.files:
                state.files = await self._plan(entry)
            state.total_bytes = sum(item["size"] for item in state.files)
            state.downloaded_bytes = sum(
                self._present_bytes(dest_dir, item) for item in state.files)
            self._progress(state)
            self._save()
            for index, item in enumerate(state.files):
                target = dest_dir / item["filename"]
                if not target.resolve().is_relative_to(dest_dir.resolve()):
                    raise ValueError("Invalid repository filename")
                present = self._present_bytes(dest_dir, item)
                await self._download_file(state, item["repo"], item["filename"], target,
                                          size=item["size"], revision=item["revision"],
                                          other_bytes=state.downloaded_bytes - present)
                state.completed_files = index + 1
            if entry.marker:
                (dest_dir / entry.marker_name).write_text(json.dumps(entry.marker, indent=2) + "\n")
            if entry.fixup:
                _apply_fixup(entry.fixup, dest_dir)
            self._mark_folder(dest_dir, "done")
            state.status = "done"
            # A finished download changes what is on disk; without this the
            # new model would not appear until the cache expired.
            from .library import invalidate_library_cache

            for hidden in settings.hidden_models:
                if Path(hidden).is_relative_to(dest_dir):
                    settings.show_model(hidden)
            invalidate_library_cache()
            state.percent = 100.0
            state.stage = "Complete"
            state.speed_bytes_s = 0
        except asyncio.CancelledError:
            state.status = "paused"
            raise
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            state.status = "error"
            state.error = str(exc)
        finally:
            state.speed_bytes_s = 0
            self._save()
            if self.on_finished and state.status in {"done", "error"}:
                self.on_finished(state)

    @staticmethod
    def _mark_folder(dest_dir: Path, status: str) -> None:
        marker = dest_dir / ".uncloud-download.json"
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps({"status": status}))
        temporary.replace(marker)

    async def _plan(self, entry: CatalogEntry) -> list[dict]:
        from huggingface_hub import HfApi

        repos = dict.fromkeys([entry.repo, *(repo for repo, _ in entry.extra_files)])
        metadata = {}
        for repo in repos:
            metadata[repo] = await asyncio.to_thread(
                HfApi().model_info, repo_id=repo, files_metadata=True)
        selected = ([(entry.repo, name) for name in entry.files] if entry.files else
                    [(entry.repo, item.rfilename) for item in metadata[entry.repo].siblings
                     if not entry.allow_patterns or any(fnmatch.fnmatch(item.rfilename, pattern)
                                                       for pattern in entry.allow_patterns)])
        selected.extend(entry.extra_files)
        out = []
        seen = set()
        for repo, name in selected:
            if name in seen:
                raise ValueError(f"Multiple download components target {name}")
            seen.add(name)
            item = next((s for s in metadata[repo].siblings if s.rfilename == name), None)
            if item is None or item.size is None or item.size < 0:
                raise ValueError(
                    f"Could not determine the download size of {name}. Retry to resume.")
            out.append({"repo": repo, "filename": name, "size": item.size,
                        "revision": metadata[repo].sha})
        if not out:
            raise ValueError("The model repository did not contain the required files.")
        return out

    @staticmethod
    def _present_bytes(dest_dir: Path, item: dict) -> int:
        target = dest_dir / item["filename"]
        if not target.resolve().is_relative_to(dest_dir.resolve()):
            raise ValueError("Invalid repository filename")
        if target.is_file():
            return min(target.stat().st_size, item["size"])
        partial = target.with_suffix(target.suffix + ".part")
        return min(partial.stat().st_size, item["size"]) if partial.is_file() else 0

    @staticmethod
    def _progress(state: DownloadState) -> None:
        state.percent = (min(99.9, state.downloaded_bytes / state.total_bytes * 100)
                         if state.total_bytes else 0)

    async def _download_file(
        self, state: DownloadState, repo: str, filename: str, dest: Path,
        *, size: int | None = None, revision: str = "main", other_bytes: int = 0,
    ) -> None:
        if dest.is_file():
            if size is None or dest.stat().st_size == size:
                return  # Completed files are never downloaded again.
            if dest.stat().st_size > size or dest.with_suffix(dest.suffix + ".part").exists():
                raise ValueError(f"The existing {filename} has an unexpected size.")
            dest.rename(dest.with_suffix(dest.suffix + ".part"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        state.stage = filename
        url = HF_RESOLVE.format(repo=repo, file=filename, revision=revision)
        tmp = dest.with_suffix(dest.suffix + ".part")
        resume_from = tmp.stat().st_size if tmp.exists() else 0
        # Manifest sizes refer to decoded repository bytes. Avoid transport
        # compression changing Content-Length or the byte offsets on resume.
        headers = {"Accept-Encoding": "identity"}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"

        token = os.environ.get("HF_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        last_tick = time.monotonic()
        last_bytes = resume_from
        state.downloaded_bytes = other_bytes + resume_from

        async with (
            httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(60, connect=20)
            ) as client,
            client.stream("GET", url, headers=headers) as resp,
        ):
            if (
                resp.status_code == 416
                and resp.headers.get("Content-Range") == f"bytes */{resume_from}"
                and (size is None or resume_from == size)
            ):
                tmp.rename(dest)
                state.downloaded_bytes = other_bytes + resume_from
                self._progress(state)
                return
            resp.raise_for_status()
            # A server may ignore Range. Never append a full response to a partial file.
            if resume_from and resp.status_code != 206:
                resume_from = 0
                state.downloaded_bytes = other_bytes
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
                    if size is not None and total != size:
                        raise ValueError(f"The server reported an unexpected size for {filename}.")
                    if not state.files:
                        state.total_bytes = total

            mode = "ab" if resume_from else "wb"
            with open(tmp, mode) as f:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
                    state.downloaded_bytes += len(chunk)
                    now = time.monotonic()
                    if now - last_tick >= 0.5:
                        transferred = state.downloaded_bytes - other_bytes - last_bytes
                        state.speed_bytes_s = transferred / (now - last_tick)
                        last_tick, last_bytes = now, state.downloaded_bytes - other_bytes
                    self._progress(state)

        expected = size if size is not None else state.total_bytes
        if expected and tmp.stat().st_size != expected:
            raise ValueError(f"The download of {filename} is incomplete. Resume to finish it.")
        tmp.rename(dest)
        self._progress(state)


download_manager = DownloadManager(CONFIG_DIR / "downloads.json")
