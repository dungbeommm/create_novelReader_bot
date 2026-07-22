"""Per-segment / per-chapter audio filtering (volume, denoise, silence)."""

from __future__ import annotations

from pathlib import Path

from ..config.models import AudioSettings
from .ffmpeg import run_ffmpeg


def build_filter_chain(cfg: AudioSettings) -> str:
    """Compose an ffmpeg ``-af`` filter chain from settings.

    Order: denoise -> silence trim (edges) -> loudness normalize. Returns an
    empty string when nothing is enabled, so callers can skip filtering.
    """
    filters: list[str] = []
    if cfg.noise_reduction:
        filters.append("afftdn=nf=-25")
    if cfg.trim_silence:
        thr = cfg.silence_threshold_db
        dur = cfg.silence_min_duration
        filters.append(
            f"silenceremove=start_periods=1:start_silence={dur}:start_threshold={thr}dB:"
            f"detection=peak"
        )
        # Reverse trick to also trim trailing silence.
        filters.append("areverse")
        filters.append(
            f"silenceremove=start_periods=1:start_silence={dur}:start_threshold={thr}dB:"
            f"detection=peak"
        )
        filters.append("areverse")
    if cfg.normalize_volume:
        filters.append(
            f"loudnorm=I={cfg.loudness_target_i}:TP={cfg.loudness_tp}:LRA={cfg.loudness_lra}"
        )
    return ",".join(filters)


def process_segment(src: Path, dst: Path, cfg: AudioSettings) -> Path:
    """Apply the configured filter chain and resample a single WAV segment."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    chain = build_filter_chain(cfg)
    args = ["-i", str(src), "-ar", str(cfg.sample_rate), "-ac", str(cfg.channels)]
    if chain:
        args += ["-af", chain]
    args.append(str(dst))
    run_ffmpeg(args)
    return dst
