"""The conversion pipeline: ebook file(s) -> finished audiobook artifacts.

This orchestrator wires together the ebook, normalize, segment, tts, audio,
cache, checkpoint and metadata services. It is deliberately free of any
Telegram or GitHub specifics so it can run identically on a laptop, in Docker
or on a GitHub Actions runner.

Fault tolerance:
- Per-segment synthesis is retried and cached (SHA256), so identical text is
  never re-rendered.
- Progress is checkpointed after every chapter; a re-run resumes instead of
  restarting.
- A soft time budget lets the caller stop cleanly before the runner is killed,
  leaving a valid checkpoint for the next dispatch.
"""

from __future__ import annotations

import time
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_fixed

from ..audio.service import AudioService
from ..cache.audio_cache import AudioCache
from ..checkpoint.store import Checkpoint, CheckpointStore
from ..config.models import Settings
from ..core.domain import Book, Chapter, ConversionOptions, ConversionResult, Voice
from ..core.enums import Stage
from ..core.errors import TimeBudgetExceeded
from ..core.interfaces import ProgressReporter
from ..ebook.service import EbookService
from ..metadata import (
    build_tags,
    ensure_cover,
    write_chapter_json,
    write_metadata_json,
    write_playlist,
)
from ..metadata.tags import embed_cover
from ..normalize.service import NormalizationService
from ..segment.segmenter import Segmenter
from ..tts.piper import PiperEngine
from ..tts.voices import VoiceScanner
from ..utils.fs import ensure_dir, slugify
from ..utils.logging import StageLogger, get_logger

logger = get_logger(__name__)


class _NullReporter:
    """No-op progress reporter used when none is supplied."""

    def report(self, stage: str, progress: float, message: str = "") -> None:  # noqa: D401
        logger.info("[%s] %.0f%% %s", stage, progress * 100, message)


class ConversionPipeline:
    """Runs the full ebook -> audiobook conversion."""

    def __init__(
        self,
        settings: Settings,
        ebook_service: EbookService,
        normalization: NormalizationService,
        segmenter: Segmenter,
        voices: VoiceScanner,
        engine: PiperEngine,
        audio: AudioService,
        cache: AudioCache,
        checkpoints: CheckpointStore,
    ) -> None:
        self._settings = settings
        self._ebook = ebook_service
        self._normalize = normalization
        self._segmenter = segmenter
        self._voices = voices
        self._engine = engine
        self._audio = audio
        self._cache = cache
        self._checkpoints = checkpoints

    def run(
        self,
        task_id: str,
        inputs: list[Path],
        options: ConversionOptions,
        reporter: ProgressReporter | None = None,
        deadline: float | None = None,
    ) -> ConversionResult:
        """Execute the pipeline for one task.

        Args:
            task_id: Unique task id (used for work dir + checkpoint).
            inputs: Source ebook/archive files.
            options: User-selected conversion options.
            reporter: Optional progress reporter (e.g. Telegram updater).
            deadline: Optional epoch seconds after which the run checkpoints and
                raises :class:`TimeBudgetExceeded` for a resume.

        Returns:
            A :class:`ConversionResult` describing all produced artifacts.
        """
        reporter = reporter or _NullReporter()
        work_dir = ensure_dir(Path(self._settings.work_dir) / task_id)
        out_dir = ensure_dir(Path(self._settings.output_dir) / task_id)
        log_path = out_dir / "conversion.log"

        voice = self._voices.get(options.voice_id)
        checkpoint = self._checkpoints.load(task_id)

        slog = StageLogger(logger, Stage.EXTRACT.value)
        reporter.report(Stage.EXTRACT.value, 0.05, "Reading ebook")
        book = self._ebook.build_book(inputs, work_dir)
        slog.info("Book '%s' with %d chapters, %d chars", book.title, book.chapter_count, book.char_count)

        cover_path = self._prepare_cover(book, out_dir)
        book.cover_path = str(cover_path) if cover_path else None

        output_files, durations, titles = self._render_chapters(
            book, voice, options, work_dir, out_dir, checkpoint, reporter, deadline
        )

        if options.merge_mode == "single" and len(output_files) > 1:
            output_files, durations, titles = self._merge_single(
                book, output_files, work_dir, out_dir, options
            )

        result = self._finalize(
            book, options, output_files, durations, titles, cover_path, out_dir, log_path
        )
        self._checkpoints.clear(task_id)
        logger.info("Cache stats: %s", self._cache.stats)
        reporter.report(Stage.CLEANUP.value, 1.0, "Done")
        return result

    # -- Stages -------------------------------------------------------------
    def _prepare_cover(self, book: Book, out_dir: Path) -> Path | None:
        return ensure_cover(book.cover_path, book.title, book.author, out_dir / "cover.jpg")

    def _render_chapters(
        self,
        book: Book,
        voice: Voice,
        options: ConversionOptions,
        work_dir: Path,
        out_dir: Path,
        checkpoint: Checkpoint,
        reporter: ProgressReporter,
        deadline: float | None,
    ) -> tuple[list[Path], list[float], list[str]]:
        output_files: list[Path] = []
        durations: list[float] = []
        titles: list[str] = []
        total = book.chapter_count

        for chapter in book.chapters:
            titles.append(chapter.title)
            encoded = out_dir / f"{chapter.slug}.{options.audio_format}"

            if checkpoint.is_chapter_done(chapter.index) and encoded.exists():
                logger.info("Skipping chapter %d (checkpoint)", chapter.index)
                output_files.append(encoded)
                durations.append(checkpoint.chapter_durations.get(str(chapter.index), 0.0))
                continue

            if deadline and time.time() > deadline:
                self._checkpoints.save(checkpoint)
                raise TimeBudgetExceeded(
                    f"Stopped before chapter {chapter.index}; checkpoint saved for resume."
                )

            progress = 0.1 + 0.8 * (chapter.index - 1) / max(total, 1)
            reporter.report(
                Stage.GENERATE_AUDIO.value, progress, f"Chapter {chapter.index}/{total}"
            )
            encoded, duration = self._render_one_chapter(
                book, chapter, voice, options, work_dir, out_dir
            )
            output_files.append(encoded)
            durations.append(duration)
            checkpoint.mark_chapter_done(chapter.index, str(encoded), duration)
            checkpoint.stage = Stage.GENERATE_AUDIO.value
            self._checkpoints.save(checkpoint)
        return output_files, durations, titles

    def _render_one_chapter(
        self,
        book: Book,
        chapter: Chapter,
        voice: Voice,
        options: ConversionOptions,
        work_dir: Path,
        out_dir: Path,
    ) -> tuple[Path, float]:
        seg_dir = ensure_dir(work_dir / "segments" / chapter.slug)
        segments = self._segmenter.segment_chapter(chapter)
        processed: list[Path] = []

        synth_params = {
            "voice": voice.id,
            "speed": options.speed,
            "sr": options.sample_rate,
            "fmt": "wav",
        }
        for segment in segments:
            normalized = self._normalize.normalize(segment.text)
            if not normalized.strip():
                continue
            processed.append(
                self._synthesize_segment(normalized, segment.index, seg_dir, voice, options, synth_params)
            )

        chapter_wav = work_dir / "chapters" / f"{chapter.slug}.wav"
        self._audio.merge_chapter(processed, chapter_wav)

        tags = build_tags(book, chapter.index, book.chapter_count, chapter.title)
        encoded = self._audio.encode_file(chapter_wav, out_dir / chapter.slug, tags)
        if book.cover_path:
            embed_cover(encoded, Path(book.cover_path))
        return encoded, self._audio.duration(encoded)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
    def _synthesize_segment(
        self,
        text: str,
        index: int,
        seg_dir: Path,
        voice: Voice,
        options: ConversionOptions,
        params: dict[str, object],
    ) -> Path:
        """Synthesize + post-process one segment, using the cache when possible."""
        processed_wav = seg_dir / f"seg_{index:05d}.wav"
        key = self._cache.key(text, params)
        if self._cache.get(key, processed_wav):
            return processed_wav

        raw_wav = seg_dir / f"seg_{index:05d}.raw.wav"
        self._engine.synthesize(text, raw_wav, voice, options.speed)
        self._audio.post_process_segment(raw_wav, processed_wav)
        raw_wav.unlink(missing_ok=True)
        self._cache.put(key, processed_wav)
        return processed_wav

    def _merge_single(
        self,
        book: Book,
        chapter_files: list[Path],
        work_dir: Path,
        out_dir: Path,
        options: ConversionOptions,
    ) -> tuple[list[Path], list[float], list[str]]:
        """Merge per-chapter files into one book-length file."""
        logger.info("Merging %d chapters into a single file", len(chapter_files))
        # Re-concatenate from encoded outputs via an intermediate WAV list.
        book_wav = work_dir / "book.wav"
        self._audio.merge_all(chapter_files, book_wav)
        base = out_dir / slugify(book.title) or out_dir / "audiobook"
        tags = build_tags(book, 1, 1)
        single = self._audio.encode_file(book_wav, base, tags)
        if book.cover_path:
            embed_cover(single, Path(book.cover_path))
        return [single], [self._audio.duration(single)], [book.title]

    def _finalize(
        self,
        book: Book,
        options: ConversionOptions,
        output_files: list[Path],
        durations: list[float],
        titles: list[str],
        cover_path: Path | None,
        out_dir: Path,
        log_path: Path,
    ) -> ConversionResult:
        reporter_stage = Stage.METADATA.value
        logger.info("[%s] Writing playlist and metadata", reporter_stage)
        playlist = write_playlist(output_files, durations, titles, out_dir / "playlist.m3u")
        chapter_json = write_chapter_json(titles, output_files, durations, out_dir / "chapter.json")
        metadata_json = write_metadata_json(
            book,
            output_files,
            sum(durations),
            options.bitrate,
            options.sample_rate,
            options.audio_format,
            out_dir / "metadata.json",
        )
        return ConversionResult(
            book_title=book.title,
            output_files=[str(f) for f in output_files],
            cover_path=str(cover_path) if cover_path else None,
            playlist_path=str(playlist),
            chapter_json_path=str(chapter_json),
            metadata_json_path=str(metadata_json),
            log_path=str(log_path) if log_path.exists() else None,
            total_duration_seconds=sum(durations),
        )
