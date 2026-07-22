"""SHA256-keyed cache of synthesized segment WAVs.

If two segments have identical normalized text *and* identical synthesis
parameters (voice + speed + engine noise settings), they produce identical
audio, so we synthesize once and reuse. This is the single biggest CPU saver
for books with repeated passages, and it survives across GitHub Actions runs
when the cache directory is restored via ``actions/cache``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..config.models import CacheSettings
from ..utils.fs import ensure_dir
from ..utils.hashing import cache_key
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AudioCache:
    """A simple, thread-safe-enough file cache for segment audio."""

    def __init__(self, settings: CacheSettings) -> None:
        self._cfg = settings
        self._dir = ensure_dir(settings.dir) if settings.enabled else Path(settings.dir)
        self._hits = 0
        self._misses = 0

    def key(self, text: str, params: dict[str, Any]) -> str:
        """Return the cache key for a segment."""
        return cache_key(text, params)

    def path_for(self, key: str) -> Path:
        """Return the on-disk cache path for a key (sharded by prefix)."""
        return self._dir / key[:2] / f"{key}.wav"

    def get(self, key: str, dst: Path) -> bool:
        """Copy a cached WAV to ``dst`` if present. Returns True on hit."""
        if not self._cfg.enabled:
            return False
        cached = self.path_for(key)
        if cached.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, dst)
            self._hits += 1
            return True
        self._misses += 1
        return False

    def put(self, key: str, src: Path) -> None:
        """Store ``src`` under ``key`` for future reuse."""
        if not self._cfg.enabled:
            return
        cached = self.path_for(key)
        cached.parent.mkdir(parents=True, exist_ok=True)
        if not cached.exists():
            shutil.copyfile(src, cached)

    @property
    def stats(self) -> dict[str, int]:
        """Return hit/miss counters for logging."""
        return {"hits": self._hits, "misses": self._misses}
