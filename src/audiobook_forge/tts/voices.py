"""Discover Piper voices on disk.

A voice is any ``*.onnx`` model with a sibling ``*.json`` (or ``*.onnx.json``)
config anywhere under the configured ``models/`` directory. Nothing is
hard-coded: dropping a new pair of files in ``models/`` makes a new voice
available automatically, including in the Telegram menu.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.domain import Voice
from ..core.errors import ConfigError
from ..utils.fs import slugify
from ..utils.logging import get_logger

logger = get_logger(__name__)


class VoiceScanner:
    """Scans a directory tree for Piper voices and resolves them by id."""

    def __init__(self, models_dir: str | Path, default_voice: str | None = None) -> None:
        self._models_dir = Path(models_dir)
        self._default_voice = default_voice

    def _config_for(self, onnx: Path) -> Path | None:
        candidates = [
            onnx.with_suffix(onnx.suffix + ".json"),  # ngoc_huyen.onnx.json
            onnx.with_suffix(".json"),                # ngoc_huyen.json
        ]
        return next((c for c in candidates if c.exists()), None)

    def _display_name(self, voice_id: str) -> str:
        return voice_id.replace("_", " ").replace("-", " ").title()

    def list_voices(self) -> list[Voice]:
        """Return every voice found under the models directory, sorted by id."""
        if not self._models_dir.exists():
            logger.warning("Models directory does not exist: %s", self._models_dir)
            return []

        voices: list[Voice] = []
        for onnx in sorted(self._models_dir.rglob("*.onnx")):
            config = self._config_for(onnx)
            if config is None:
                logger.warning("Skipping %s: no matching .json config found", onnx.name)
                continue
            # Use the file stem verbatim as the stable voice id so it matches
            # what the user dropped into models/ (e.g. "ngoc_huyen"). It is also
            # Telegram-callback-safe. slugify() is only used for display fallback.
            voice_id = onnx.stem
            language, sample_rate = self._read_config(config)
            voices.append(
                Voice(
                    id=voice_id,
                    display_name=self._display_name(voice_id),
                    onnx_path=str(onnx),
                    config_path=str(config),
                    language=language,
                    sample_rate=sample_rate,
                )
            )
        logger.info("Discovered %d voice(s) in %s", len(voices), self._models_dir)
        return voices

    @staticmethod
    def _read_config(config: Path) -> tuple[str, int]:
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "", 22050
        language = ""
        espeak = data.get("espeak") or {}
        if isinstance(espeak, dict):
            language = str(espeak.get("voice", ""))
        language = language or str((data.get("language") or {}).get("code", "")) if isinstance(
            data.get("language"), dict
        ) else language
        sample_rate = int((data.get("audio") or {}).get("sample_rate", 22050))
        return language, sample_rate

    def get(self, voice_id: str | None) -> Voice:
        """Resolve a voice by id, falling back to default / first available."""
        voices = self.list_voices()
        if not voices:
            raise ConfigError(
                f"No Piper voices found in '{self._models_dir}'. Add a *.onnx model "
                "plus its *.json config (see models/README.md)."
            )
        wanted = voice_id or self._default_voice
        if wanted:
            for voice in voices:
                if voice.id == wanted:
                    return voice
            logger.warning("Voice '%s' not found; using first available.", wanted)
        return voices[0]

    def default_voice_id(self) -> str | None:
        """Return the id of the default voice, or ``None`` if none are present."""
        voices = self.list_voices()
        if not voices:
            return None
        if self._default_voice:
            for voice in voices:
                if voice.id == self._default_voice:
                    return voice.id
        return voices[0].id
