"""Generate playlist / chapter / metadata sidecar files.

Three artifacts are produced next to the audio output:

* ``playlist.m3u`` - an extended M3U playlist (players read it in order).
* ``chapter.json`` - a machine-readable chapter list with cumulative offsets.
* ``metadata.json`` - book-level metadata (title, author, counts, duration,
  bitrate, sample rate, per-file breakdown).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.domain import Book
from ..utils.logging import get_logger

logger = get_logger(__name__)


def _fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def write_playlist(
    files: list[Path],
    durations: list[float],
    titles: list[str],
    dst: Path,
) -> Path:
    """Write an extended ``.m3u`` playlist referencing files by relative name."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    for file, duration, title in zip(files, durations, titles):
        lines.append(f"#EXTINF:{int(round(duration))},{title}")
        lines.append(file.name)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote playlist: %s (%d entries)", dst, len(files))
    return dst


def write_chapter_json(
    titles: list[str],
    files: list[Path],
    durations: list[float],
    dst: Path,
) -> Path:
    """Write ``chapter.json`` with per-chapter start/end offsets in seconds."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    chapters = []
    offset = 0.0
    for index, (title, file, duration) in enumerate(zip(titles, files, durations), start=1):
        chapters.append(
            {
                "index": index,
                "title": title,
                "file": file.name,
                "start": round(offset, 3),
                "end": round(offset + duration, 3),
                "duration": round(duration, 3),
                "duration_human": _fmt_duration(duration),
            }
        )
        offset += duration
    payload = {"chapter_count": len(chapters), "chapters": chapters}
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote chapter index: %s", dst)
    return dst


def write_metadata_json(
    book: Book,
    files: list[Path],
    total_duration: float,
    bitrate: int,
    sample_rate: int,
    audio_format: str,
    dst: Path,
) -> Path:
    """Write book-level ``metadata.json`` describing the finished audiobook."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": book.title,
        "author": book.author or "Unknown",
        "language": book.language or "",
        "chapter_count": book.chapter_count,
        "file_count": len(files),
        "files": [f.name for f in files],
        "total_duration_seconds": round(total_duration, 3),
        "total_duration_human": _fmt_duration(total_duration),
        "format": audio_format,
        "bitrate_kbps": bitrate,
        "sample_rate_hz": sample_rate,
        "generator": "Audiobook Forge",
    }
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote metadata: %s", dst)
    return dst
