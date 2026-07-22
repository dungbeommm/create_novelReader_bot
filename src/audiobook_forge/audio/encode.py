"""Concatenation and final encoding to the requested container/codec."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..config.models import AudioSettings
from .ffmpeg import run_ffmpeg

# Map output format -> (ffmpeg codec, file extension).
_CODECS: dict[str, tuple[str, str]] = {
    "mp3": ("libmp3lame", "mp3"),
    "wav": ("pcm_s16le", "wav"),
    "opus": ("libopus", "opus"),
    "m4a": ("aac", "m4a"),
    "aac": ("aac", "aac"),
}


def concat_wavs(segments: list[Path], dst_wav: Path) -> Path:
    """Loss-lessly concatenate WAV segments using ffmpeg's concat demuxer."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as listing:
        for seg in segments:
            listing.write(f"file '{seg.resolve().as_posix()}'\n")
        list_path = listing.name
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", str(dst_wav)])
    finally:
        Path(list_path).unlink(missing_ok=True)
    return dst_wav


def encode(src: Path, dst_base: Path, cfg: AudioSettings, metadata: dict[str, str] | None = None) -> Path:
    """Encode ``src`` into the configured format, embedding metadata tags.

    Args:
        src: Source audio (typically a merged WAV).
        dst_base: Destination path *without* extension.
        cfg: Audio settings (format, bitrate, sample rate...).
        metadata: Optional tag map (title/artist/album/track...).

    Returns:
        Final encoded file path (with correct extension).
    """
    codec, ext = _CODECS[cfg.format]
    dst = dst_base.with_suffix(f".{ext}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    args = ["-i", str(src), "-vn", "-ar", str(cfg.sample_rate), "-ac", str(cfg.channels), "-c:a", codec]
    if cfg.format != "wav":
        args += ["-b:a", f"{cfg.bitrate}k"]
    for key, value in (metadata or {}).items():
        if value:
            args += ["-metadata", f"{key}={value}"]
    args.append(str(dst))
    run_ffmpeg(args)
    return dst
