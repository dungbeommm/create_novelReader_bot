"""Deterministic hashing helpers used by the audio cache."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def cache_key(text: str, params: dict[str, Any]) -> str:
    """Return a stable key for a normalized segment + synthesis parameters.

    Identical text rendered with identical parameters yields an identical key,
    which is what allows the audio cache to skip re-synthesis.
    """
    payload = json.dumps({"t": text, "p": params}, sort_keys=True, ensure_ascii=False)
    return sha256_text(payload)
