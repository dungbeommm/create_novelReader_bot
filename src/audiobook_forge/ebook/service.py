"""High-level ebook intake service.

Ties together archive expansion, format detection and per-format extraction,
and merges multiple inputs into a single logical :class:`Book` when needed
(e.g. a zip of numbered ``.txt`` chapters).
"""

from __future__ import annotations

from pathlib import Path

from ..core.domain import Book, Chapter
from ..core.errors import ExtractionError, UnsupportedFormatError
from ..utils.logging import get_logger
from .archive import collect_ebooks
from .extractors import DEFAULT_EXTRACTORS, BaseExtractor

logger = get_logger(__name__)


class EbookService:
    """Turns raw user uploads into one merged :class:`Book`."""

    def __init__(self, extractors: tuple[BaseExtractor, ...] = DEFAULT_EXTRACTORS) -> None:
        self._extractors = extractors

    def _find_extractor(self, path: Path) -> BaseExtractor:
        for extractor in self._extractors:
            if extractor.supports(path):
                return extractor
        raise UnsupportedFormatError(f"No extractor for file: {path.name}")

    def extract_one(self, path: Path) -> Book:
        """Extract a single (already de-archived) ebook file."""
        extractor = self._find_extractor(path)
        logger.info("Extracting %s with %s", path.name, type(extractor).__name__)
        return extractor.extract(path)

    def build_book(self, inputs: list[Path], workdir: Path, title: str | None = None) -> Book:
        """Expand archives, extract every ebook, and merge into one book.

        A single ebook is returned as-is. Multiple ebooks are concatenated in
        filename order, with each source contributing one or more chapters.

        Args:
            inputs: User-provided files (ebooks/archives).
            workdir: Scratch directory for extraction.
            title: Optional override for the merged book title.

        Returns:
            A merged :class:`Book` with globally re-indexed chapters.
        """
        ebook_files = collect_ebooks(inputs, workdir)
        if not ebook_files:
            raise ExtractionError("No supported ebook files were found in the upload.")

        logger.info("Found %d ebook file(s) to process", len(ebook_files))
        books = [self.extract_one(path) for path in ebook_files]

        if len(books) == 1:
            book = books[0]
            if title:
                book.title = title
            self._reindex(book)
            return book

        merged = Book(
            title=title or books[0].title,
            author=books[0].author,
            language=books[0].language,
            source_path=str(ebook_files[0]),
            cover_path=next((b.cover_path for b in books if b.cover_path), None),
        )
        for book in books:
            merged.chapters.extend(book.chapters)
        self._reindex(merged)
        logger.info("Merged %d books into %d chapters", len(books), merged.chapter_count)
        return merged

    @staticmethod
    def _reindex(book: Book) -> None:
        reindexed: list[Chapter] = []
        for i, chapter in enumerate(book.chapters, start=1):
            chapter.index = i
            reindexed.append(chapter)
        book.chapters = reindexed
