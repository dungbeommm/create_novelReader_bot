"""Load and merge configuration from YAML + environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models import Settings

DEFAULT_CONFIG_PATH = "config/default.yaml"
_ENV_CONFIG_KEY = "AUDIOBOOK_FORGE_CONFIG"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a mapping at the top level.")
    return data


def _split_csv_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Overlay environment-driven values (mostly deployment + secrets-adjacent).

    Secrets themselves (tokens) are never stored in Settings; they are read at
    the edge by the Telegram/GitHub clients straight from the environment.
    """
    data.setdefault("github", {})
    data.setdefault("telegram", {})

    if repo := os.getenv("GITHUB_REPOSITORY"):
        data["github"]["repository"] = repo
    if wf := os.getenv("GITHUB_WORKFLOW_FILE"):
        data["github"]["workflow_file"] = wf
    if ref := os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_REF"):
        data["github"]["ref"] = ref.replace("refs/heads/", "")
    if ids := os.getenv("TELEGRAM_ALLOWED_USER_IDS"):
        data["telegram"]["allowed_user_ids"] = _split_csv_ints(ids)
    if level := os.getenv("LOG_LEVEL"):
        data["log_level"] = level
    return data


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """Build a validated :class:`Settings` from YAML + environment.

    Args:
        config_path: Optional explicit path. Falls back to ``$AUDIOBOOK_FORGE_CONFIG``
            then :data:`DEFAULT_CONFIG_PATH`.

    Returns:
        A fully validated settings object.
    """
    load_dotenv(override=False)
    path = Path(config_path or os.getenv(_ENV_CONFIG_KEY, DEFAULT_CONFIG_PATH))
    data = _read_yaml(path)
    data = _apply_env_overrides(data)
    return Settings.model_validate(data)
