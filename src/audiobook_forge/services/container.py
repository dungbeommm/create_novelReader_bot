"""Dependency-injection container (composition root).

Centralising construction keeps the wiring in one place and makes it trivial to
swap an implementation (e.g. a different TTS engine or a Redis-backed queue)
without editing the pipeline or the adapters.
"""

from __future__ import annotations

from functools import cached_property

from ..audio.service import AudioService
from ..cache.audio_cache import AudioCache
from ..checkpoint.store import CheckpointStore
from ..config.models import Settings
from ..ebook.service import EbookService
from ..normalize.service import NormalizationService
from ..pipelines.conversion import ConversionPipeline
from ..queue.task_queue import TaskQueue
from ..segment.segmenter import Segmenter
from ..tts.piper import PiperEngine
from ..tts.voices import VoiceScanner


class Container:
    """Lazily constructs and memoizes application services."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @cached_property
    def ebook_service(self) -> EbookService:
        return EbookService()

    @cached_property
    def normalization(self) -> NormalizationService:
        return NormalizationService(self.settings.normalization)

    @cached_property
    def segmenter(self) -> Segmenter:
        return Segmenter(self.settings.segmentation)

    @cached_property
    def voices(self) -> VoiceScanner:
        return VoiceScanner(self.settings.tts.models_dir, self.settings.tts.default_voice)

    @cached_property
    def engine(self) -> PiperEngine:
        return PiperEngine(self.settings.tts.noise_scale, self.settings.tts.noise_w)

    @cached_property
    def audio(self) -> AudioService:
        return AudioService(self.settings.audio)

    @cached_property
    def cache(self) -> AudioCache:
        return AudioCache(self.settings.cache)

    @cached_property
    def checkpoints(self) -> CheckpointStore:
        return CheckpointStore(self.settings.queue.dir + "/checkpoints")

    @cached_property
    def queue(self) -> TaskQueue:
        return TaskQueue(self.settings.queue)

    @cached_property
    def pipeline(self) -> ConversionPipeline:
        return ConversionPipeline(
            settings=self.settings,
            ebook_service=self.ebook_service,
            normalization=self.normalization,
            segmenter=self.segmenter,
            voices=self.voices,
            engine=self.engine,
            audio=self.audio,
            cache=self.cache,
            checkpoints=self.checkpoints,
        )
