"""Tests for multi-pattern chapter detection."""

from __future__ import annotations

from audiobook_forge.ebook.chapters import detect_chapters


def test_detects_vietnamese_numeric() -> None:
    text = "Ch\u01b0\u01a1ng 1\nN\u1ed9i dung m\u1ed9t.\n\nCh\u01b0\u01a1ng 2\nN\u1ed9i dung hai."
    chapters = detect_chapters(text)
    assert len(chapters) == 2
    assert chapters[0].title.startswith("Ch\u01b0\u01a1ng 1")


def test_detects_roman_and_chapter_word() -> None:
    text = "Ch\u01b0\u01a1ng I\nA\n\nChapter II\nB\n\nCh\u01b0\u01a1ng III\nC"
    chapters = detect_chapters(text)
    assert len(chapters) == 3


def test_detects_cjk() -> None:
    text = "\u7b2c1\u7ae0\n\u5185\u5bb9\n\n\u7b2c2\u7ae0\n\u5185\u5bb9"
    chapters = detect_chapters(text)
    assert len(chapters) == 2


def test_fallback_single_chapter() -> None:
    text = "Just some prose with no chapter markers at all."
    chapters = detect_chapters(text)
    assert len(chapters) == 1
    assert chapters[0].text


def test_preserves_order_and_index() -> None:
    text = "Ph\u1ea7n 1\nA\n\nPh\u1ea7n 2\nB\n\nPh\u1ea7n 3\nC"
    chapters = detect_chapters(text)
    assert [c.index for c in chapters] == [1, 2, 3]
