"""MOBI / AZW / AZW3 extractor.

These Amazon formats are not natively parseable with pure-Python libraries in
a reliable way. When the Calibre ``ebook-convert`` binary is available we
transcode to EPUB first and delegate to :class:`EpubExtractor`; otherwise we
raise a clear, actionable error.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ...core.domain import Book
from ...core.errors import UnsupportedFormatError
from ...utils.logging import get_logger
from .base import BaseExtractor
from .epub import EpubExtractor

logger = get_logger(__name__)


class MobiExtractor(BaseExtractor):
    """Handles ``.mobi`` / ``.azw`` / ``.azw3`` via Calibre when present."""

    extensions = frozenset({".mobi", ".azw", ".azw3"})

    def extract(self, path: Path) -> Book:
        converter = shutil.which("ebook-convert")
        if converter is None:
            raise UnsupportedFormatError(
                f"Reading {path.suffix} requires Calibre's 'ebook-convert' binary. "
                "Install Calibre (the Docker image and CI workflow do this) or "
                "convert the file to EPUB/TXT first."
            )
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / (path.stem + ".epub")
            logger.info("Converting %s -> EPUB via Calibre", path.name)
            subprocess.run(
                [converter, str(path), str(epub_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            book = EpubExtractor().extract(epub_path)
        book.source_path = str(path)
        return book
