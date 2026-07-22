"""Split chapter text into TTS-friendly segments.

Piper degrades on very long inputs, so we chunk text on sentence boundaries and
never cut mid-sentence. Chunks respect a soft character target, a hard char cap
and an approximate token cap. Optional sentence overlap improves prosody
continuity between consecutive segments.
"""

from __future__ import annotations

import re

from ..config.models import SegmentationSettings
from ..core.domain import Chapter, Segment

# Sentence terminators include Latin and CJK/Vietnamese punctuation.
_SENTENCE_END = re.compile(r"(?<=[\.\!\?\u2026\u3002\uff01\uff1f])\s+|\n+")
_ABBREV_GUARD = re.compile(r"\b(?:tp|ts|bs|gs|mr|mrs|dr|vs|st|no)\.$", re.IGNORECASE)


class Segmenter:
    """Turns a :class:`Chapter` into an ordered list of :class:`Segment`."""

    def __init__(self, settings: SegmentationSettings) -> None:
        self._cfg = settings

    def split_sentences(self, text: str) -> list[str]:
        """Split text into sentences, guarding against common abbreviations."""
        raw = _SENTENCE_END.split(text.strip())
        sentences: list[str] = []
        for part in raw:
            part = part.strip()
            if not part:
                continue
            if sentences and _ABBREV_GUARD.search(sentences[-1]):
                # Merge false split caused by an abbreviation dot.
                sentences[-1] = f"{sentences[-1]} {part}"
            else:
                sentences.append(part)
        return sentences

    @staticmethod
    def _token_count(text: str) -> int:
        return len(text.split())

    def _hard_wrap(self, sentence: str) -> list[str]:
        """Break a single over-long sentence at the hard character cap.

        Prefers to break at a space near the cap so words stay intact.
        """
        cap = self._cfg.max_chars
        pieces: list[str] = []
        remaining = sentence.strip()
        while len(remaining) > cap:
            window = remaining[:cap]
            cut = window.rfind(" ")
            if cut < int(cap * 0.6):
                cut = cap
            pieces.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            pieces.append(remaining)
        return pieces

    def segment_text(self, text: str) -> list[str]:
        """Chunk arbitrary text into segment strings."""
        sentences = self.split_sentences(text)
        chunks: list[str] = []
        buffer: list[str] = []
        length = 0

        def flush() -> None:
            nonlocal buffer, length
            if buffer:
                chunk = " ".join(buffer).strip()
                if len(chunk) >= self._cfg.min_chars:
                    chunks.append(chunk)
                buffer = []
                length = 0

        for sentence in sentences:
            for piece in (self._hard_wrap(sentence) if len(sentence) > self._cfg.max_chars else [sentence]):
                piece_len = len(piece)
                would_exceed = (
                    length + piece_len > self._cfg.max_chars
                    or self._token_count(" ".join(buffer + [piece])) > self._cfg.max_tokens
                )
                if buffer and would_exceed:
                    flush()
                buffer.append(piece)
                length += piece_len + 1
                if length >= self._cfg.soft_chars:
                    flush()
        flush()
        return self._apply_overlap(chunks)

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        overlap = self._cfg.overlap_sentences
        if overlap <= 0 or len(chunks) < 2:
            return chunks
        out: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = self.split_sentences(chunks[i - 1])[-overlap:]
            out.append((" ".join(prev_tail) + " " + chunks[i]).strip())
        return out

    def segment_chapter(self, chapter: Chapter) -> list[Segment]:
        """Populate and return ``chapter.segments``."""
        segments = [
            Segment(index=i, text=chunk)
            for i, chunk in enumerate(self.segment_text(chapter.text), start=1)
        ]
        chapter.segments = segments
        return segments
