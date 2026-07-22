"""Plain-text extractor with encoding sniffing and chapter detection."""

from __future__ import annotations

from pathlib import Path

from ...core.domain import Book
from ..chapters import detect_chapters
from .base import BaseExtractor

_ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "cp1258", "latin-1")


def read_text_best_effort(path: Path) -> str:
    """Read a text file trying several encodings, never raising on bad bytes."""
    raw = path.read_bytes()
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


class TxtExtractor(BaseExtractor):
    """Handles ``.txt`` / ``.text`` files."""

    extensions = frozenset({".txt", ".text"})

    def extract(self, path: Path) -> Book:
        text = read_text_best_effort(path)
        title = self._title_from_path(path)
        chapters = detect_chapters(text, fallback_title=title)
        return Book(title=title, source_path=str(path), chapters=chapters)
