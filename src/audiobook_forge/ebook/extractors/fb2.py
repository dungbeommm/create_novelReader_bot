"""FictionBook (FB2) extractor.

FB2 is an XML format. We parse ``<body>/<section>`` elements to recover chapter
structure and titles, ignoring binary/style nodes.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from ...core.domain import Book, Chapter
from ..chapters import detect_chapters
from .base import BaseExtractor
from .txt import read_text_best_effort


class Fb2Extractor(BaseExtractor):
    """Handles ``.fb2`` files."""

    extensions = frozenset({".fb2"})

    def extract(self, path: Path) -> Book:
        raw = read_text_best_effort(path)
        soup = BeautifulSoup(raw, "xml")

        title = self._title(soup) or self._title_from_path(path)
        author = self._author(soup)
        language = ""
        lang_tag = soup.find("lang")
        if lang_tag and lang_tag.text:
            language = lang_tag.text.strip()

        chapters: list[Chapter] = []
        body = soup.find("body")
        if body is not None:
            for section in body.find_all("section", recursive=True):
                chapter_title = ""
                title_tag = section.find("title")
                if title_tag:
                    chapter_title = title_tag.get_text(" ", strip=True)
                paragraphs = [p.get_text(" ", strip=True) for p in section.find_all("p")]
                text = "\n".join(p for p in paragraphs if p)
                if text:
                    chapters.append(
                        Chapter(
                            index=len(chapters) + 1,
                            title=chapter_title or f"Chapter {len(chapters) + 1}",
                            text=text,
                        )
                    )

        if not chapters:
            plain = soup.get_text("\n", strip=True)
            chapters = detect_chapters(plain, fallback_title=title)

        return Book(
            title=title,
            author=author,
            language=language,
            source_path=str(path),
            chapters=chapters,
        )

    @staticmethod
    def _title(soup: BeautifulSoup) -> str:
        tag = soup.find("book-title")
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _author(soup: BeautifulSoup) -> str:
        author = soup.find("author")
        if not author:
            return ""
        first = author.find("first-name")
        last = author.find("last-name")
        parts = [t.get_text(strip=True) for t in (first, last) if t]
        return " ".join(p for p in parts if p)
