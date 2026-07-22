"""File-format detection based on extension + magic bytes."""

from __future__ import annotations

from pathlib import Path

EBOOK_EXTENSIONS = {
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".xhtml",
    ".epub",
    ".fb2",
    ".mobi",
    ".azw",
    ".azw3",
}

ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".cbz"}

_MAGIC = {
    b"PK\x03\x04": "zip",
    b"7z\xbc\xaf\x27\x1c": "7z",
    b"Rar!\x1a\x07": "rar",
}


def sniff_magic(path: Path) -> str | None:
    """Return an archive type inferred from magic bytes, or ``None``."""
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return None
    for signature, kind in _MAGIC.items():
        if head.startswith(signature):
            return kind
    return None


def is_archive(path: Path) -> bool:
    """True when ``path`` looks like a supported archive.

    EPUB is a ZIP too, so we deliberately exclude ebook extensions before
    treating a ZIP magic match as an archive to unpack.
    """
    if path.suffix.lower() in EBOOK_EXTENSIONS:
        return False
    if path.suffix.lower() in ARCHIVE_EXTENSIONS:
        return True
    return sniff_magic(path) is not None


def is_ebook(path: Path) -> bool:
    """True when ``path`` has a recognised ebook extension."""
    return path.suffix.lower() in EBOOK_EXTENSIONS
