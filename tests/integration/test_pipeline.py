"""Integration test for the text side of the pipeline.

This exercises the real ebook -> normalize -> segment path end to end (no Piper
or ffmpeg required), which is the deterministic, logic-heavy portion of the
system. Audio synthesis/encoding is covered separately and needs the ffmpeg +
Piper binaries, so it is skipped when they are unavailable.
"""

from __future__ import annotations

from pathlib import Path

from audiobook_forge.config.models import NormalizationSettings, SegmentationSettings
from audiobook_forge.ebook.service import EbookService
from audiobook_forge.normalize.service import NormalizationService
from audiobook_forge.segment.segmenter import Segmenter


def test_txt_to_segments(tmp_path: Path) -> None:
    book_txt = tmp_path / "book.txt"
    book_txt.write_text(
        "Ch\u01b0\u01a1ng 1\n"
        "Nh\u00e2n v\u1eadt ch\u00ednh \u0111i 100km v\u1ec1 qu\u00ea l\u00fac 8h s\u00e1ng.\n\n"
        "Ch\u01b0\u01a1ng 2\n"
        "H\u1ecd g\u1eb7p nhau v\u00e0o ng\u00e0y 20/11 v\u1edbi 50% ni\u1ec1m vui.\n",
        encoding="utf-8",
    )

    work = tmp_path / "work"
    work.mkdir()
    book = EbookService().build_book([book_txt], work)
    assert book.chapter_count == 2

    normalizer = NormalizationService(NormalizationSettings())
    segmenter = Segmenter(SegmentationSettings(max_chars=200, soft_chars=120, min_chars=1))

    total_segments = 0
    for chapter in book.chapters:
        for segment in segmenter.segment_chapter(chapter):
            spoken = normalizer.normalize(segment.text)
            assert spoken.strip()
            total_segments += 1
    assert total_segments >= 2


def test_multiple_txt_merge_order(tmp_path: Path) -> None:
    (tmp_path / "02.txt").write_text("Ph\u1ea7n hai n\u1ed9i dung.", encoding="utf-8")
    (tmp_path / "01.txt").write_text("Ph\u1ea7n m\u1ed9t n\u1ed9i dung.", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    book = EbookService().build_book([tmp_path / "02.txt", tmp_path / "01.txt"], work)
    full_text = "\n".join(c.text for c in book.chapters)
    assert full_text.index("m\u1ed9t") < full_text.index("hai")
