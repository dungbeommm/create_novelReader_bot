"""Typed exception hierarchy.

Using a single base class lets adapters (Telegram, CLI, worker) present clean
error messages while still distinguishing recoverable from fatal conditions.
"""

from __future__ import annotations


class AudiobookForgeError(Exception):
    """Base class for all application errors."""


class ConfigError(AudiobookForgeError):
    """Raised when configuration is missing or invalid."""


class UnsupportedFormatError(AudiobookForgeError):
    """Raised when an input file format is not supported."""


class ExtractionError(AudiobookForgeError):
    """Raised when ebook text extraction fails."""


class TTSFailure(AudiobookForgeError):
    """Raised when the TTS engine cannot synthesize a segment."""


class AudioProcessingError(AudiobookForgeError):
    """Raised when ffmpeg-based processing fails."""


class ReleaseError(AudiobookForgeError):
    """Raised when publishing a GitHub Release fails."""


class TimeBudgetExceeded(AudiobookForgeError):
    """Raised internally to trigger a checkpoint + re-dispatch (resume)."""
