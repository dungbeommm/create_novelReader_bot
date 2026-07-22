"""Thin wrappers around the ffmpeg / ffprobe binaries.

Centralising subprocess handling keeps error reporting consistent and makes the
rest of the audio code easy to read and to unit test (by mocking these calls).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..core.errors import AudioProcessingError
from ..utils.logging import get_logger

logger = get_logger(__name__)


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioProcessingError(f"Required binary '{name}' not found on PATH.")
    return path


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with ``-y`` and consistent quiet logging."""
    cmd = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args]
    logger.debug("ffmpeg %s", " ".join(args))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioProcessingError(f"ffmpeg failed: {result.stderr.strip()}")


def probe_duration(path: Path) -> float:
    """Return the duration of a media file in seconds (0.0 on failure)."""
    cmd = [
        _binary("ffprobe"),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0
