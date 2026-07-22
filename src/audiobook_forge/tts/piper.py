"""Piper TTS engine wrapper.

Loads a voice model once and reuses it for every segment (models are the
expensive part). Compatible with both the piper-tts 1.2.x ``synthesize`` API
and the newer ``synthesize_wav`` API.
"""

from __future__ import annotations

import wave
from pathlib import Path

from ..core.domain import Voice
from ..core.errors import TTSFailure
from ..utils.logging import get_logger

logger = get_logger(__name__)

try:
    from piper import PiperVoice
except Exception:  # pragma: no cover - optional at import time
    PiperVoice = None  # type: ignore[assignment]


class PiperEngine:
    """Thin, cached wrapper around :class:`piper.PiperVoice`."""

    def __init__(self, noise_scale: float = 0.667, noise_w: float = 0.8) -> None:
        self._noise_scale = noise_scale
        self._noise_w = noise_w
        self._loaded_id: str | None = None
        self._voice_obj: object | None = None

    def _ensure_loaded(self, voice: Voice) -> object:
        if PiperVoice is None:
            raise TTSFailure("piper-tts is not installed in this environment.")
        if self._loaded_id != voice.id or self._voice_obj is None:
            logger.info("Loading Piper voice '%s' (%s)", voice.id, Path(voice.onnx_path).name)
            self._voice_obj = PiperVoice.load(voice.onnx_path, config_path=voice.config_path)
            self._loaded_id = voice.id
        return self._voice_obj

    def synthesize(self, text: str, out_wav: Path, voice: Voice, speed: float) -> Path:
        """Synthesize ``text`` to ``out_wav`` using ``voice`` at ``speed``.

        Args:
            text: Already-normalized segment text.
            out_wav: Destination WAV path (parent dirs created as needed).
            voice: Resolved voice to use.
            speed: length_scale; > 1.0 is slower, < 1.0 is faster.

        Returns:
            The path to the written WAV file.
        """
        if not text.strip():
            raise TTSFailure("Refusing to synthesize empty text.")
        voice_obj = self._ensure_loaded(voice)
        out_wav.parent.mkdir(parents=True, exist_ok=True)

        kwargs = {
            "length_scale": speed,
            "noise_scale": self._noise_scale,
            "noise_w": self._noise_w,
        }
        try:
            with wave.open(str(out_wav), "wb") as wav_file:
                if hasattr(voice_obj, "synthesize_wav"):
                    voice_obj.synthesize_wav(text, wav_file)  # type: ignore[attr-defined]
                else:
                    voice_obj.synthesize(text, wav_file, **kwargs)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - surface as domain error
            raise TTSFailure(f"Piper synthesis failed: {exc}") from exc
        return out_wav
