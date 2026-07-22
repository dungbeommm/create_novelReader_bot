"""Language-agnostic chapter detection for plain text.

Rather than relying on a single regex, we score a set of heading patterns
(Vietnamese, English, CJK, roman numerals, parts/volumes...) and split on the
union of matches. This is resilient to mixed conventions inside one book.
"""

from __future__ import annotations

import re

from ..core.domain import Chapter

# Each pattern must match at the START of a stripped line.
_HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Vietnamese: "Chương 1", "Chương I", "CHƯƠNG MƯỜI"
    re.compile(r"^ch(?:uong|\u01b0\u01a1ng)\s+[\dIVXLCDM\w]", re.IGNORECASE),
    # "Phần 1", "Quyển 2"
    re.compile(r"^(?:ph(?:an|\u1ea7n)|quy(?:en|\u1ec3n))\s+[\dIVXLCDM]", re.IGNORECASE),
    # English: "Chapter 1", "Part IV", "Book Two", "Volume 3", "Section 5"
    re.compile(r"^(?:chapter|part|book|volume|section)\s+[\dIVXLCDM\w]", re.IGNORECASE),
    # CJK: "第1章", "第十二章", "第3回", "卷一"
    re.compile(r"^\u7b2c\s*[\d\u4e00-\u9fff]+\s*[\u7ae0\u56de\u8282\u90e8\u5377]"),
    re.compile(r"^\u5377\s*[\d\u4e00-\u9fff]+"),
    # Bare numeric heading on its own short line: "12." or "12"
    re.compile(r"^\d{1,4}\s*[\.\)\uff0e\u3001]?\s*$"),
)

_MAX_HEADING_LEN = 90


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return False
    return any(pattern.match(stripped) for pattern in _HEADING_PATTERNS)


def detect_chapters(text: str, fallback_title: str = "Chapter") -> list[Chapter]:
    """Split raw text into chapters.

    If no headings are detected the whole text becomes a single chapter, so the
    caller never has to special-case heading-less documents.

    Args:
        text: Full document text.
        fallback_title: Title used for content before the first heading and for
            the single-chapter fallback.

    Returns:
        Ordered list of :class:`Chapter` with 1-based indices.
    """
    lines = text.splitlines()
    chapters: list[Chapter] = []
    current_title = fallback_title
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            chapters.append(Chapter(index=len(chapters) + 1, title=current_title, text=body))

    for line in lines:
        if _looks_like_heading(line):
            flush()
            buffer = []
            current_title = line.strip()
        else:
            buffer.append(line)
    flush()

    if not chapters:
        body = text.strip()
        if body:
            chapters.append(Chapter(index=1, title=fallback_title, text=body))
    return chapters
