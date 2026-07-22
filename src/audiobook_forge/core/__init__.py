"""Framework-agnostic domain model, enums, errors and interfaces.

The ``core`` package is the innermost layer of the Clean Architecture. It has
no dependency on any I/O, third-party service, or framework, so it can be unit
tested trivially and reused by any adapter.
"""

from __future__ import annotations

from .domain import (
    Book,
    Chapter,
    ConversionOptions,
    ConversionResult,
    Segment,
    Task,
    Voice,
)
from .enums import TaskStatus
from .errors import (
    AudiobookForgeError,
    ConfigError,
    ExtractionError,
    ReleaseError,
    TTSFailure,
    UnsupportedFormatError,
)

__all__ = [
    "Book",
    "Chapter",
    "ConversionOptions",
    "ConversionResult",
    "Segment",
    "Task",
    "Voice",
    "TaskStatus",
    "AudiobookForgeError",
    "ConfigError",
    "ExtractionError",
    "ReleaseError",
    "TTSFailure",
    "UnsupportedFormatError",
]
