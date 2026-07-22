"""Filesystem helpers with safe, portable behaviour."""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SLUG_TRIM = re.compile(r"^-+|-+$")


def ensure_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents) if missing and return it as :class:`Path`."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def reset_dir(path: str | Path) -> Path:
    """Remove ``path`` if present, then recreate it empty."""
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def slugify(value: str, max_length: int = 60) -> str:
    """ASCII, lower-case, hyphenated slug suitable for filenames.

    Vietnamese diacritics are folded to ASCII so filenames stay portable across
    filesystems and GitHub Release asset naming rules.
    """
    value = value.replace("\u0111", "d").replace("\u0110", "D")
    normalized = unicodedata.normalize("NFKD", value)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", ascii_str)
    slug = _SLUG_TRIM.sub("", slug)
    return slug[:max_length].strip("-")


def human_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
