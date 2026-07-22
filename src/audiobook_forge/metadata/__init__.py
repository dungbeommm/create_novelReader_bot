"""Metadata, cover art and playlist generation."""

from __future__ import annotations

from .cover import ensure_cover
from .playlist import write_chapter_json, write_metadata_json, write_playlist
from .tags import build_tags

__all__ = [
    "ensure_cover",
    "write_playlist",
    "write_chapter_json",
    "write_metadata_json",
    "build_tags",
]
