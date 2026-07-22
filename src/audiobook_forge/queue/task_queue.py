"""A durable, file-backed task queue.

Designed to be simple and dependency-free so it works both for the long-running
Telegram bot (tracking user tasks and history) and inside GitHub Actions. Each
task is one JSON file; a lock file guards concurrent writers. Ordering is by
creation time.

For high-scale deployments this port can be swapped for Redis/SQS without
touching callers, thanks to the narrow method surface.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..config.models import QueueSettings
from ..core.domain import Task
from ..core.enums import TaskStatus
from ..utils.fs import ensure_dir
from ..utils.logging import get_logger

logger = get_logger(__name__)


class _FileLock:
    """Best-effort cross-process lock using atomic directory creation."""

    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self._path = path
        self._timeout = timeout

    def __enter__(self) -> "_FileLock":
        deadline = time.time() + self._timeout
        while True:
            try:
                os.mkdir(self._path)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    logger.warning("Lock timeout; forcing acquisition of %s", self._path)
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        try:
            os.rmdir(self._path)
        except OSError:
            pass


class TaskQueue:
    """Persist and query :class:`Task` objects on disk."""

    def __init__(self, settings: QueueSettings) -> None:
        self._cfg = settings
        self._dir = ensure_dir(settings.dir)
        self._lock_path = self._dir / ".lock"

    def _task_path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.json"

    def enqueue(self, task: Task) -> Task:
        """Persist a new task in QUEUED state."""
        with _FileLock(self._lock_path):
            self._write(task)
        logger.info("Enqueued task %s for user %s", task.id, task.user_id)
        return task

    def _write(self, task: Task) -> None:
        task.touch()
        path = self._task_path(task.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def update(self, task: Task) -> None:
        """Persist changes to an existing task."""
        with _FileLock(self._lock_path):
            self._write(task)

    def get(self, task_id: str) -> Task | None:
        """Load a single task by id, or ``None`` if missing."""
        path = self._task_path(task_id)
        if not path.exists():
            return None
        return Task.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_tasks(self, user_id: int | None = None) -> list[Task]:
        """Return all tasks (optionally filtered by user), newest last."""
        tasks: list[Task] = []
        for path in self._dir.glob("*.json"):
            try:
                task = Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            if user_id is None or task.user_id == user_id:
                tasks.append(task)
        tasks.sort(key=lambda t: t.created_at)
        return tasks

    def next_queued(self) -> Task | None:
        """Return the oldest task still in QUEUED state."""
        queued = [t for t in self.list_tasks() if t.status == TaskStatus.QUEUED]
        return queued[0] if queued else None

    def cancel(self, task_id: str) -> bool:
        """Mark a non-terminal task as cancelled. Returns True if changed."""
        task = self.get(task_id)
        if task is None or task.status.is_terminal:
            return False
        task.status = TaskStatus.CANCELLED
        task.message = "Cancelled by user."
        self.update(task)
        return True

    def prune_history(self) -> None:
        """Trim completed tasks beyond ``max_history`` (oldest first)."""
        terminal = [t for t in self.list_tasks() if t.status.is_terminal]
        excess = len(terminal) - self._cfg.max_history
        for task in terminal[: max(0, excess)]:
            self._task_path(task.id).unlink(missing_ok=True)
