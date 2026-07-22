"""Configuration loading and typed settings models."""

from __future__ import annotations

from .loader import load_settings
from .models import (
    AudioSettings,
    CacheSettings,
    GitHubSettings,
    NormalizationSettings,
    QueueSettings,
    ReleaseSettings,
    SegmentationSettings,
    Settings,
    TelegramSettings,
    TTSSettings,
)

__all__ = [
    "load_settings",
    "Settings",
    "AudioSettings",
    "CacheSettings",
    "GitHubSettings",
    "NormalizationSettings",
    "QueueSettings",
    "ReleaseSettings",
    "SegmentationSettings",
    "TelegramSettings",
    "TTSSettings",
]
