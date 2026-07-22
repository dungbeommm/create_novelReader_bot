"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from audiobook_forge.config.models import (
    NormalizationSettings,
    SegmentationSettings,
)


@pytest.fixture()
def segmentation_settings() -> SegmentationSettings:
    return SegmentationSettings(max_chars=120, soft_chars=100, min_chars=10)


@pytest.fixture()
def normalization_settings() -> NormalizationSettings:
    return NormalizationSettings()
