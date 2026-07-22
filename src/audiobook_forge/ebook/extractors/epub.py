"""EPUB extractor.

Reads spine order + navigation to preserve correct chapter sequence, extracts
metadata (title/author/language/cover) and converts each XHTML document into
clean text with HTML and CSS removed.
"""

from __future__ import annotations

from pathlib import Path

from ...core.domain import Book, Chapter
from ...core.errors import ExtractionError
from ...utils.logging import get_logger
from .base import BaseExtractor
from .html import html_to_text

logger = get_logger(__name__)

try:
    import ebooklib
    from ebooklib import epub
except Exception:  # pragma: no cover - optional
    ebooklib = None  # type: ignore[assignment]
    epub = None  # type: ignore[assignment]


class EpubExtractor(BaseExtractor):
    """Handles ``.epub`` files."""

    extensions = frozenset({".epub"})

    def extract(self, path: Path) -> Book:
        if epub is None:
            raise ExtractionError("EbookLib is not installed; cannot read EPUB files.")
        book = epub.read_epub(str(path))

        title = self._meta(book, "title") or self._title_from_path(path)
        author = self._meta(book, "creator")
        language = self._meta(book, "language")
        cover_path = self._extract_cover(book, path)

        chapters: list[Chapter] = []
        for item_id, _ in book.spine:
            item = book.get_item_with_id(item_id)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            html = item.get_content().decode("utf-8", errors="replace")
            text = html_to_text(html)
            if not text.strip():
                continue
            chapter_title = self._first_line_title(text, len(chapters) + 1)
            chapters.append(
                Chapter(index=len(chapters) + 1, title=chapter_title, text=text)
            )

        if not chapters:
            raise ExtractionError(f"No readable content found in EPUB: {path.name}")

        return Book(
            title=title,
            author=author,
            language=language,
            source_path=str(path),
            cover_path=cover_path,
            chapters=chapters,
        )

    @staticmethod
    def _meta(book: "epub.EpubBook", name: str) -> str:
        values = book.get_metadata("DC", name)
        if values and values[0] and values[0][0]:
            return str(values[0][0]).strip()
        return ""

    @staticmethod
    def _first_line_title(text: str, index: int) -> str:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first and len(first) <= 90:
            return first
        return f"Chapter {index}"

    def _extract_cover(self, book: "epub.EpubBook", path: Path) -> str | None:
        try:
            for item in book.get_items_of_type(ebooklib.ITEM_COVER):
                return self._write_cover(item.get_content(), path)
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if "cover" in (item.get_name() or "").lower():
                    return self._write_cover(item.get_content(), path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Cover extraction failed: %s", exc)
        return None

    @staticmethod
    def _write_cover(data: bytes, path: Path) -> str:
        cover = path.with_suffix(".cover.jpg")
        cover.write_bytes(data)
        return str(cover)
