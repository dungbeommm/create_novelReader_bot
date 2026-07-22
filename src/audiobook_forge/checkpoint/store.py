"""Checkpointing so a conversion can resume after a runner timeout.

The checkpoint records which chapters/segments are already rendered and encoded.
Combined with the content-addressed audio cache, a re-dispatched job skips all
completed work and continues from where it stopped -- it never starts over.

The checkpoint file lives inside the run's work dir and is also uploaded as a
GitHub Actions artifact / restored via cache so it survives across runs.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..utils.fs import ensure_dir
from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Checkpoint:
    """Serializable progress record for a single task."""

    task_id: str
    completed_chapters: list[int] = field(default_factory=list)
    encoded_files: list[str] = field(default_factory=list)
    chapter_durations: dict[str, float] = field(default_factory=dict)
    stage: str = ""
    updated_at: float = 0.0

    def mark_chapter_done(self, index: int, output_file: str, duration: float) -> None:
        if index not in self.completed_chapters:
            self.completed_chapters.append(index)
        if output_file and output_file not in self.encoded_files:
            self.encoded_files.append(output_file)
        self.chapter_durations[str(index)] = duration

    def is_chapter_done(self, index: int) -> bool:
        return index in self.completed_chapters

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CheckpointStore:
    """Loads/saves :class:`Checkpoint` atomically as JSON."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = ensure_dir(directory)

    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.checkpoint.json"

    def load(self, task_id: str) -> Checkpoint:
        """Load an existing checkpoint or return a fresh one."""
        path = self._path(task_id)
        if not path.exists():
            return Checkpoint(task_id=task_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info("Resuming from checkpoint: %d chapter(s) done", len(data.get("completed_chapters", [])))
            return Checkpoint(**data)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Corrupt checkpoint ignored (%s); starting fresh.", exc)
            return Checkpoint(task_id=task_id)

    def save(self, checkpoint: Checkpoint) -> None:
        """Persist a checkpoint atomically (write-temp-then-rename)."""
        import time

        checkpoint.updated_at = time.time()
        path = self._path(checkpoint.task_id)
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(checkpoint.to_dict(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def clear(self, task_id: str) -> None:
        self._path(task_id).unlink(missing_ok=True)
