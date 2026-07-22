"""Tests for the file-backed task queue."""

from __future__ import annotations

from pathlib import Path

from audiobook_forge.config.models import QueueSettings
from audiobook_forge.core.domain import Task
from audiobook_forge.core.enums import TaskStatus
from audiobook_forge.queue.task_queue import TaskQueue


def _queue(tmp_path: Path) -> TaskQueue:
    return TaskQueue(QueueSettings(dir=str(tmp_path / "q"), max_history=3))


def test_enqueue_get_update(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    task = Task(user_id=1, chat_id=2, user_name="Dung")
    queue.enqueue(task)
    loaded = queue.get(task.id)
    assert loaded is not None
    assert loaded.user_id == 1

    loaded.status = TaskStatus.RUNNING
    queue.update(loaded)
    assert queue.get(task.id).status == TaskStatus.RUNNING


def test_next_queued_is_oldest(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    a = Task(user_id=1, chat_id=1, created_at=1.0)
    b = Task(user_id=1, chat_id=1, created_at=2.0)
    queue.enqueue(b)
    queue.enqueue(a)
    assert queue.next_queued().id == a.id


def test_cancel(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    task = Task(user_id=1, chat_id=1)
    queue.enqueue(task)
    assert queue.cancel(task.id) is True
    assert queue.get(task.id).status == TaskStatus.CANCELLED
    assert queue.cancel(task.id) is False
