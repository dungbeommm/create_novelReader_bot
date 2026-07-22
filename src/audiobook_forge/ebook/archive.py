"""Recursive archive extraction (zip / 7z / rar).

Archives may contain multiple ebooks and/or nested archives. This module
flattens everything into a list of concrete ebook files on disk, preserving
name order so that, e.g., a zip of numbered ``.txt`` chapters is merged in the
right sequence downstream.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from ..core.errors import ExtractionError
from ..utils.logging import get_logger
from .detector import ARCHIVE_EXTENSIONS, is_archive, is_ebook, sniff_magic

logger = get_logger(__name__)

try:  # optional dependency
    import py7zr
except Exception:  # pragma: no cover - optional
    py7zr = None  # type: ignore[assignment]

try:  # optional dependency (needs the `unrar`/`unar` binary for many archives)
    import rarfile
except Exception:  # pragma: no cover - optional
    rarfile = None  # type: ignore[assignment]


def _extract_zip(path: Path, dest: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        archive.extractall(dest)


def _extract_7z(path: Path, dest: Path) -> None:
    if py7zr is None:
        raise ExtractionError("py7zr is not installed; cannot open .7z archives.")
    with py7zr.SevenZipFile(path, mode="r") as archive:
        archive.extractall(path=dest)


def _extract_rar(path: Path, dest: Path) -> None:
    if rarfile is None:
        raise ExtractionError("rarfile is not installed; cannot open .rar archives.")
    try:
        with rarfile.RarFile(path) as archive:
            archive.extractall(dest)
    except rarfile.RarCannotExec as exc:  # pragma: no cover - depends on host
        raise ExtractionError(
            "RAR support requires the 'unrar' or 'unar' binary on PATH."
        ) from exc


def _archive_kind(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in ARCHIVE_EXTENSIONS:
        return {".zip": "zip", ".cbz": "zip", ".7z": "7z", ".rar": "rar"}[suffix]
    return sniff_magic(path)


def extract_archive(path: Path, dest: Path) -> None:
    """Extract a single archive into ``dest`` based on its detected kind."""
    kind = _archive_kind(path)
    logger.info("Extracting %s archive: %s", kind, path.name)
    if kind == "zip":
        _extract_zip(path, dest)
    elif kind == "7z":
        _extract_7z(path, dest)
    elif kind == "rar":
        _extract_rar(path, dest)
    else:
        raise ExtractionError(f"Unknown archive type: {path.name}")


def collect_ebooks(inputs: list[Path], workdir: Path, _depth: int = 0) -> list[Path]:
    """Recursively expand archives and return an ordered list of ebook files.

    Args:
        inputs: Files provided by the user (ebooks and/or archives).
        workdir: Scratch directory for extracted archive contents.
        _depth: Internal recursion guard against archive bombs / cycles.

    Returns:
        Ebook file paths sorted case-insensitively by name for stable ordering.
    """
    if _depth > 8:
        raise ExtractionError("Archive nesting too deep (possible archive bomb).")

    ebooks: list[Path] = []
    for item in inputs:
        if not item.exists():
            logger.warning("Skipping missing input: %s", item)
            continue
        if is_archive(item):
            sub_dest = workdir / f"extract_{item.stem}_{_depth}"
            sub_dest.mkdir(parents=True, exist_ok=True)
            extract_archive(item, sub_dest)
            nested = sorted(
                (p for p in sub_dest.rglob("*") if p.is_file()),
                key=lambda p: p.as_posix().lower(),
            )
            ebooks.extend(collect_ebooks(nested, workdir, _depth + 1))
        elif is_ebook(item):
            ebooks.append(item)
        else:
            logger.debug("Ignoring non-ebook file: %s", item.name)

    ebooks.sort(key=lambda p: p.name.lower())
    return ebooks
