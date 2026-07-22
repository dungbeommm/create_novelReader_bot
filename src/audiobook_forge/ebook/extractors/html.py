"""HTML / XHTML extractor.

Strips scripts, styles and tags to recover clean readable text, then applies
chapter detection based on heading tags first, falling back to text heuristics.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from ...core.domain import Book, Chapter
from ..chapters import detect_chapters
from .base import BaseExtractor
from .txt import read_text_best_effort

_BLOCK_TAGS = {"p", "div", "section", "article", "li", "blockquote", "br", "tr"}
_HEADING_TAGS = ("h1", "h2", "h3")


def html_to_text(html: str) -> str:
    """Convert an HTML fragment/document into clean plain text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "noscript", "svg"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    text = soup.get_text()
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class HtmlExtractor(BaseExtractor):
    """Handles ``.html`` / ``.htm`` / ``.xhtml`` files."""

    extensions = frozenset({".html", ".htm", ".xhtml"})

    def extract(self, path: Path) -> Book:
        html = read_text_best_effort(path)
        title = self._title_from_path(path)
        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip() or title

        chapters = self._split_by_headings(soup)
        if not chapters:
            chapters = detect_chapters(html_to_text(html), fallback_title=title)
        return Book(title=title, source_path=str(path), chapters=chapters)

    def _split_by_headings(self, soup: BeautifulSoup) -> list[Chapter]:
        headings = soup.find_all(_HEADING_TAGS)
        if len(headings) < 2:
            return []
        chapters: list[Chapter] = []
        for heading in headings:
            title = heading.get_text(strip=True) or f"Chapter {len(chapters) + 1}"
            parts: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in _HEADING_TAGS:
                    break
                parts.append(str(sibling))
            body = html_to_text("".join(parts))
            if body:
                chapters.append(Chapter(index=len(chapters) + 1, title=title, text=body))
        return chapters
