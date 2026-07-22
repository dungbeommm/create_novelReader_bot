"""Base class shared by all extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ...core.domain import Book


class BaseExtractor(ABC):
    """Abstract ebook extractor.

    Subclasses declare the extensions they handle and implement :meth:`extract`.
    """

    #: Lower-case file extensions (with leading dot) this extractor handles.
    extensions: frozenset[str] = frozenset()

    def supports(self, path: Path) -> bool:
        """Whether this extractor can handle ``path``."""
        return path.suffix.lower() in self.extensions

    @abstractmethod
    def extract(self, path: Path) -> Book:
        """Parse ``path`` into a :class:`Book`."""
        raise NotImplementedError

    @staticmethod
    def _title_from_path(path: Path) -> str:
        return path.stem.replace("_", " ").strip() or "Audiobook"
