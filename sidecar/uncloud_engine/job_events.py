"""Optional completion hook shared by product job engines; never carries content."""

from __future__ import annotations

import logging

on_finished = None


def finished(kind, job):
    if on_finished and job.status in {"done", "error"}:
        try:
            on_finished(kind, job.id, job.status)
        except Exception:
            logging.getLogger(__name__).warning("A completion notification could not be saved")
