"""Tests for dynamic Piper voice discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiobook_forge.tts.voices import VoiceScanner


def _make_voice(root: Path, name: str, nested: bool = True) -> None:
    base = root / name if nested else root
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{name}.onnx").write_bytes(b"fake-model")
    (base / f"{name}.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": 22050}, "language": {"code": "vi"}}),
        encoding="utf-8",
    )


def test_discovers_nested_and_flat(tmp_path: Path) -> None:
    _make_voice(tmp_path, "ngoc_huyen", nested=True)
    _make_voice(tmp_path, "model_a", nested=False)
    scanner = VoiceScanner(str(tmp_path))
    ids = {v.id for v in scanner.list_voices()}
    assert "ngoc_huyen" in ids
    assert "model_a" in ids


def test_get_by_id_and_default(tmp_path: Path) -> None:
    _make_voice(tmp_path, "ngoc_huyen", nested=True)
    scanner = VoiceScanner(str(tmp_path))
    voice = scanner.get("ngoc_huyen")
    assert voice.sample_rate == 22050
    assert scanner.default_voice_id() == "ngoc_huyen"


def test_missing_voice_raises(tmp_path: Path) -> None:
    _make_voice(tmp_path, "ngoc_huyen", nested=True)
    scanner = VoiceScanner(str(tmp_path))
    with pytest.raises(Exception):
        scanner.get("does_not_exist")
