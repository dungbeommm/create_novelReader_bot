"""Abstract ports (interfaces) implemented by outer-layer adapters.

Defining these Protocols keeps the pipeline decoupled from concrete engines,
so, for example, Piper can be swapped for another TTS backend without touching
orchestration code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .domain import Book, Voice


@runtime_checkable
class EbookExtractor(Protocol):
    """Parses a single ebook file into a :class:`Book`."""

    def supports(self, path: Path) -> bool: ...

    def extract(self, path: Path) -> Book: ...


@runtime_checkable
class TextNormalizer(Protocol):
    """Cleans raw text so a TTS engine reads it naturally."""

    def normalize(self, text: str) -> str: ...


@runtime_checkable
class TTSEngine(Protocol):
    """Synthesizes text to a WAV file."""

    def synthesize(self, text: str, out_wav: Path, voice: Voice, speed: float) -> Path: ...


@runtime_checkable
class VoiceRegistry(Protocol):
    """Discovers and resolves installed voices."""

    def list_voices(self) -> list[Voice]: ...

    def get(self, voice_id: str | None) -> Voice: ...


@runtime_checkable
class ReleasePublisher(Protocol):
    """Publishes final artifacts somewhere the user can download them."""

    def publish(self, tag: str, name: str, files: list[Path], body: str) -> str: ...


@runtime_checkable
class ProgressReporter(Protocol):
    """Receives progress updates from the pipeline."""

    def report(self, stage: str, progress: float, message: str = "") -> None: ...
