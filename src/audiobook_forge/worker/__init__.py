"""GitHub Actions worker entrypoint."""

from __future__ import annotations

from .run_job import run_job

__all__ = ["run_job"]
