"""Immutable / lightweight domain objects.

These dataclasses model the problem domain and are serializable to JSON so
they can travel through the queue, checkpoints and GitHub Actions payloads.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .enums import TaskStatus


def new_id(prefix: str) -> str:
    """Return a short, sortable, unique id such as ``task_1a2b3c4d``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Voice:
    """A Piper voice discovered on disk."""

    id: str
    display_name: str
    onnx_path: str
    config_path: str
    language: str = ""
    sample_rate: int = 22050

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Segment:
    """A TTS-sized chunk of a chapter."""

    index: int
    text: str
    char_count: int = 0

    def __post_init__(self) -> None:
        if not self.char_count:
            self.char_count = len(self.text)


@dataclass(slots=True)
class Chapter:
    """A single chapter of a book."""

    index: int
    title: str
    text: str
    segments: list[Segment] = field(default_factory=list)

    @property
    def slug(self) -> str:
        """Filesystem-safe base name, e.g. ``0007_chuong-7``."""
        from ..utils.fs import slugify

        return f"{self.index:04d}_{slugify(self.title) or 'chapter'}"


@dataclass(slots=True)
class Book:
    """A parsed ebook ready for synthesis."""

    title: str
    author: str = ""
    language: str = ""
    source_path: str = ""
    cover_path: str | None = None
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    @property
    def char_count(self) -> int:
        return sum(len(c.text) for c in self.chapters)


@dataclass(slots=True)
class ConversionOptions:
    """User-selected options for a single conversion.

    Mirrors the Telegram inline-keyboard choices. Every field has a safe default
    so a conversion can run headless.
    """

    voice_id: str | None = None
    speed: float = 1.0
    audio_format: str = "mp3"
    bitrate: int = 128
    sample_rate: int = 22050
    merge_mode: str = "per_chapter"  # or "single"
    compress: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversionOptions:
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


@dataclass(slots=True)
class Task:
    """A unit of work tracked by the queue and persisted across runs."""

    id: str = field(default_factory=lambda: new_id("task"))
    user_id: int = 0
    chat_id: int = 0
    user_name: str = ""
    source_files: list[str] = field(default_factory=list)
    options: ConversionOptions = field(default_factory=ConversionOptions)
    status: TaskStatus = TaskStatus.QUEUED
    progress: float = 0.0
    stage: str = ""
    message: str = ""
    release_url: str = ""
    intake_ref: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempts: int = 0

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["options"] = self.options.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        data = dict(data)
        data["status"] = TaskStatus(data.get("status", TaskStatus.QUEUED.value))
        data["options"] = ConversionOptions.from_dict(data.get("options", {}))
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


@dataclass(slots=True)
class ConversionResult:
    """Outputs of a completed conversion, prior to release."""

    book_title: str
    output_files: list[str] = field(default_factory=list)
    cover_path: str | None = None
    playlist_path: str | None = None
    chapter_json_path: str | None = None
    metadata_json_path: str | None = None
    log_path: str | None = None
    total_duration_seconds: float = 0.0
    release_url: str = ""
