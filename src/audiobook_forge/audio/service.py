"""Coordinates the audio stage of the pipeline.

Responsibilities:
- Post-process each synthesized segment WAV (volume, denoise, silence).
- Merge segments into per-chapter WAVs.
- Encode to the requested output format with tags.
- Optionally merge all chapters into a single file.
"""

from __future__ import annotations

from pathlib import Path

from ..config.models import AudioSettings
from ..utils.logging import get_logger
from .encode import concat_wavs, encode
from .ffmpeg import probe_duration
from .processing import process_segment

logger = get_logger(__name__)


class AudioService:
    """Turns raw segment WAVs into finished, tagged audio files."""

    def __init__(self, settings: AudioSettings) -> None:
        self._cfg = settings

    def post_process_segment(self, raw_wav: Path, processed_wav: Path) -> Path:
        """Filter + resample one segment; returns the processed path."""
        return process_segment(raw_wav, processed_wav, self._cfg)

    def merge_chapter(self, segment_wavs: list[Path], chapter_wav: Path) -> Path:
        """Concatenate processed segment WAVs into one chapter WAV."""
        return concat_wavs(segment_wavs, chapter_wav)

    def encode_file(self, src_wav: Path, dst_base: Path, metadata: dict[str, str]) -> Path:
        """Encode a WAV into the configured output format with metadata."""
        return encode(src_wav, dst_base, self._cfg, metadata)

    def merge_all(self, chapter_wavs: list[Path], book_wav: Path) -> Path:
        """Concatenate every chapter WAV into a single-file audiobook WAV."""
        return concat_wavs(chapter_wavs, book_wav)

    @staticmethod
    def duration(path: Path) -> float:
        """Return media duration in seconds."""
        return probe_duration(path)
