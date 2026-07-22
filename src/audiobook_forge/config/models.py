"""Typed configuration models.

Every tunable knob in the system lives here. Nothing is hard-coded in the
pipeline modules; they always receive a validated :class:`Settings` instance.

Values come from three layers, merged in increasing priority:

1. Built-in defaults declared on these Pydantic models.
2. A YAML config file (``config/default.yaml`` by default).
3. Environment variables / ``.env`` (for secrets and deployment overrides).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AudioFormat = Literal["mp3", "wav", "opus", "m4a", "aac"]
MergeMode = Literal["per_chapter", "single"]


class TTSSettings(BaseModel):
    """Piper TTS engine settings."""

    models_dir: str = Field("models", description="Directory scanned for Piper voices.")
    default_voice: str | None = Field(
        None, description="Voice id used when none is chosen. Defaults to first found."
    )
    speed: float = Field(1.0, ge=0.3, le=3.0, description="length_scale (higher = slower).")
    noise_scale: float = Field(0.667, ge=0.0, le=2.0)
    noise_w: float = Field(0.8, ge=0.0, le=2.0)
    sentence_silence: float = Field(0.35, ge=0.0, le=5.0, description="Seconds between segments.")
    allowed_speeds: list[float] = Field(
        default_factory=lambda: [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]
    )

    @field_validator("speed")
    @classmethod
    def _round_speed(cls, value: float) -> float:
        return round(value, 3)


class SegmentationSettings(BaseModel):
    """Controls how chapter text is split into TTS-friendly segments."""

    max_chars: int = Field(600, ge=80, le=5000, description="Hard character cap per segment.")
    soft_chars: int = Field(400, ge=40, description="Preferred size; flush at sentence end past this.")
    max_tokens: int = Field(240, ge=20, description="Approximate whitespace-token cap per segment.")
    overlap_sentences: int = Field(0, ge=0, le=3, description="Sentence overlap between segments.")
    min_chars: int = Field(1, ge=1, description="Drop segments shorter than this after trim.")


class NormalizationSettings(BaseModel):
    """Text normalization toggles."""

    unicode_form: Literal["NFC", "NFKC", "NFD", "NFKD"] = "NFC"
    strip_html: bool = True
    strip_markdown: bool = True
    strip_bbcode: bool = True
    decode_html_entities: bool = True
    remove_emoji: bool = True
    collapse_whitespace: bool = True
    normalize_punctuation: bool = True
    language: str = Field("vi", description="Language code driving locale-specific rules.")
    expand_vietnamese: bool = True
    extra_rules: list[str] = Field(
        default_factory=list, description="Dotted import paths of custom Rule callables."
    )


class AudioSettings(BaseModel):
    """Audio post-processing and encoding settings."""

    format: AudioFormat = "mp3"
    bitrate: int = Field(128, description="kbps for lossy formats.")
    sample_rate: int = Field(22050, description="Output sample rate in Hz.")
    channels: int = Field(1, ge=1, le=2)
    merge_mode: MergeMode = "per_chapter"
    normalize_volume: bool = True
    loudness_target_i: float = Field(-16.0, description="EBU R128 integrated loudness target (LUFS).")
    loudness_tp: float = Field(-1.5, description="True-peak ceiling (dBTP).")
    loudness_lra: float = Field(11.0, description="Loudness range target.")
    trim_silence: bool = True
    silence_threshold_db: float = Field(-45.0, description="Below this is treated as silence.")
    silence_min_duration: float = Field(0.6, description="Seconds of silence trimmed at edges.")
    noise_reduction: bool = Field(False, description="Apply ffmpeg afftdn denoiser if enabled.")
    allowed_formats: list[AudioFormat] = Field(
        default_factory=lambda: ["mp3", "wav", "opus", "m4a", "aac"]
    )
    allowed_bitrates: list[int] = Field(default_factory=lambda: [64, 96, 128, 192, 256, 320])
    allowed_sample_rates: list[int] = Field(default_factory=lambda: [22050, 24000, 44100, 48000])


class CacheSettings(BaseModel):
    """Segment-level audio cache settings (SHA256 of normalized text + params)."""

    enabled: bool = True
    dir: str = Field(".cache/audio", description="Directory holding cached segment WAVs.")
    hash_algorithm: Literal["sha256"] = "sha256"


class QueueSettings(BaseModel):
    """Task queue settings."""

    dir: str = Field("state/queue", description="Directory backing the file queue.")
    max_concurrent: int = Field(1, ge=1, description="Concurrent conversions per worker.")
    max_history: int = Field(200, ge=1, description="Completed tasks retained in history.")


class ReleaseSettings(BaseModel):
    """GitHub Release packaging settings."""

    zip_threshold: int = Field(100, ge=1, description="Zip outputs when file count >= this.")
    include_log: bool = True
    include_cover: bool = True
    include_playlist: bool = True
    tag_prefix: str = "audiobook"
    draft: bool = False
    prerelease: bool = False


class CompressionSettings(BaseModel):
    """Result compression settings."""

    enabled: bool = False
    format: Literal["zip", "7z"] = "zip"
    level: int = Field(5, ge=0, le=9)


class GitHubSettings(BaseModel):
    """GitHub API / Actions integration."""

    repository: str = Field("", description="owner/name; usually from env in Actions.")
    workflow_file: str = "convert.yml"
    ref: str = "main"
    api_url: str = "https://api.github.com"
    intake_tag_prefix: str = "inbox"
    runner_time_budget_seconds: int = Field(
        18000, description="Soft budget before the job checkpoints and re-dispatches (5h)."
    )


class TelegramSettings(BaseModel):
    """Telegram bot behaviour."""

    allowed_user_ids: list[int] = Field(default_factory=list)
    max_upload_mb: int = Field(50, description="Max single-file size accepted from Telegram.")
    media_group_wait_seconds: float = Field(2.0, description="Debounce for multi-file albums.")
    default_language: str = "vi"


class Settings(BaseModel):
    """Root settings object passed throughout the application."""

    app_name: str = "Audiobook Forge"
    work_dir: str = Field("work", description="Scratch dir for a single conversion run.")
    output_dir: str = Field("out", description="Where finished audiobooks are assembled.")
    log_level: str = "INFO"

    tts: TTSSettings = Field(default_factory=TTSSettings)
    segmentation: SegmentationSettings = Field(default_factory=SegmentationSettings)
    normalization: NormalizationSettings = Field(default_factory=NormalizationSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    release: ReleaseSettings = Field(default_factory=ReleaseSettings)
    compression: CompressionSettings = Field(default_factory=CompressionSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)

    model_config = {"extra": "forbid"}
