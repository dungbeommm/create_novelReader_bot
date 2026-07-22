"""Tests for the SHA256 content-addressed audio cache."""

from __future__ import annotations

from pathlib import Path

from audiobook_forge.cache.audio_cache import AudioCache
from audiobook_forge.config.models import CacheSettings


def _cache(tmp_path: Path) -> AudioCache:
    return AudioCache(CacheSettings(enabled=True, dir=str(tmp_path / "cache")))


def test_key_is_stable_and_param_sensitive(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    k1 = cache.key("hello", {"voice": "a", "speed": 1.0})
    k2 = cache.key("hello", {"voice": "a", "speed": 1.0})
    k3 = cache.key("hello", {"voice": "a", "speed": 1.1})
    assert k1 == k2
    assert k1 != k3


def test_put_then_get_roundtrip(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    src = tmp_path / "seg.wav"
    src.write_bytes(b"RIFFfake-wav-data")
    key = cache.key("text", {"voice": "a"})
    cache.put(key, src)

    dst = tmp_path / "restored.wav"
    assert cache.get(key, dst) is True
    assert dst.read_bytes() == b"RIFFfake-wav-data"


def test_miss_returns_false(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    dst = tmp_path / "out.wav"
    assert cache.get("nonexistent", dst) is False
    assert not dst.exists()


def test_disabled_cache_never_hits(tmp_path: Path) -> None:
    cache = AudioCache(CacheSettings(enabled=False, dir=str(tmp_path / "c")))
    src = tmp_path / "seg.wav"
    src.write_bytes(b"data")
    key = cache.key("t", {})
    cache.put(key, src)
    assert cache.get(key, tmp_path / "o.wav") is False
