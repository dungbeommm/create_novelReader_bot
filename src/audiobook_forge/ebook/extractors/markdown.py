"""Markdown extractor.

Markdown headings (``#``/``##``) define chapters; inline markup is removed by
the normalization layer, but we strip the most common constructs here so the
chapter bodies are already readable.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...core.domain import Book, Chapter
from ..chapters import detect_chapters
from .base import BaseExtractor
from .txt import read_text_best_effort

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_FENCE = re.compile(r"^```")


class MarkdownExtractor(BaseExtractor):
    """Handles ``.md`` / ``.markdown`` files."""

    extensions = frozenset({".md", ".markdown"})

    def extract(self, path: Path) -> Book:
        text = read_text_best_effort(path)
        title = self._title_from_path(path)
        chapters = self._split_by_headings(text)
        if not chapters:
            chapters = detect_chapters(text, fallback_title=title)
        return Book(title=title, source_path=str(path), chapters=chapters)

    def _split_by_headings(self, text: str) -> list[Chapter]:
        chapters: list[Chapter] = []
        current_title = ""
        buffer: list[str] = []
        in_fence = False

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body and current_title:
                chapters.append(Chapter(index=len(chapters) + 1, title=current_title, text=body))

        for line in text.splitlines():
            if _FENCE.match(line.strip()):
                in_fence = not in_fence
                buffer.append(line)
                continue
            match = _HEADING.match(line) if not in_fence else None
            if match:
                flush()
                buffer = []
                current_title = match.group(2).strip()
            else:
                buffer.append(line)
        flush()
        return chapters
