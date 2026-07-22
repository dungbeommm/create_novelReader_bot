"""Tests for checkpoint persistence and resume semantics."""

from __future__ import annotations

from pathlib import Path

from audiobook_forge.checkpoint.store import CheckpointStore


def test_roundtrip(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    cp = store.load("task-1")
    assert cp.completed_chapters == []

    cp.mark_chapter_done(1, "/out/c1.mp3", 12.5)
    cp.mark_chapter_done(2, "/out/c2.mp3", 30.0)
    store.save(cp)

    reloaded = store.load("task-1")
    assert reloaded.is_chapter_done(1)
    assert reloaded.is_chapter_done(2)
    assert not reloaded.is_chapter_done(3)
    assert reloaded.chapter_durations["1"] == 12.5


def test_clear(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    cp = store.load("task-2")
    cp.mark_chapter_done(1, "x", 1.0)
    store.save(cp)
    store.clear("task-2")
    assert store.load("task-2").completed_chapters == []


def test_corrupt_checkpoint_is_ignored(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    (tmp_path / "task-3.checkpoint.json").write_text("{not valid json", encoding="utf-8")
    cp = store.load("task-3")
    assert cp.completed_chapters == []
