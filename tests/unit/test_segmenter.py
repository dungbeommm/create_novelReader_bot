"""Tests for sentence/paragraph-aware segmentation."""

from __future__ import annotations

from audiobook_forge.config.models import SegmentationSettings
from audiobook_forge.core.domain import Chapter
from audiobook_forge.segment.segmenter import Segmenter


def test_never_exceeds_hard_limit() -> None:
    settings = SegmentationSettings(max_chars=90, soft_chars=80, min_chars=5)
    seg = Segmenter(settings)
    text = ". ".join(f"Sentence number {i} here" for i in range(40)) + "."
    chapter = Chapter(index=1, title="C1", text=text)
    segments = seg.segment_chapter(chapter)
    assert segments
    assert all(len(s.text) <= settings.max_chars for s in segments)


def test_does_not_cut_midsentence() -> None:
    settings = SegmentationSettings(max_chars=80, soft_chars=40, min_chars=5)
    seg = Segmenter(settings)
    text = "C\u00e2u m\u1ed9t ho\u00e0n ch\u1ec9nh. C\u00e2u hai c\u0169ng ho\u00e0n ch\u1ec9nh. C\u00e2u ba n\u1eefa."
    chapter = Chapter(index=1, title="C1", text=text)
    segments = seg.segment_chapter(chapter)
    joined = " ".join(s.text for s in segments)
    assert "C\u00e2u m\u1ed9t ho\u00e0n ch\u1ec9nh." in joined
    # Every segment should end on sentence-final punctuation (no mid-sentence cut).
    assert all(s.text.rstrip()[-1] in ".!?\u2026" for s in segments)


def test_indices_are_sequential() -> None:
    seg = Segmenter(SegmentationSettings(max_chars=80, soft_chars=40, min_chars=1))
    chapter = Chapter(index=1, title="C1", text="A. B. C. D. E. F. G. H.")
    segments = seg.segment_chapter(chapter)
    assert [s.index for s in segments] == list(range(1, len(segments) + 1))
