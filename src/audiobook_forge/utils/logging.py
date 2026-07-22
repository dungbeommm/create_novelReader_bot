"""Structured, consistent logging setup.

A single :func:`setup_logging` call configures the root logger. Modules obtain
child loggers via :func:`get_logger`. :class:`StageLogger` adds a per-stage
prefix and can mirror lines into a run log file that ships inside the release.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    """Configure root logging once.

    Args:
        level: Logging level name (``DEBUG``/``INFO``/...).
        log_file: Optional path that also receives all log records.
    """
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())

    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(handler)
        _CONFIGURED = True

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger."""
    return logging.getLogger(name)


class StageLogger:
    """Convenience wrapper that tags messages with the current pipeline stage."""

    def __init__(self, logger: logging.Logger, stage: str) -> None:
        self._logger = logger
        self._stage = stage

    def info(self, msg: str, *args: object) -> None:
        self._logger.info(f"[{self._stage}] {msg}", *args)

    def warning(self, msg: str, *args: object) -> None:
        self._logger.warning(f"[{self._stage}] {msg}", *args)

    def error(self, msg: str, *args: object) -> None:
        self._logger.error(f"[{self._stage}] {msg}", *args)

    def debug(self, msg: str, *args: object) -> None:
        self._logger.debug(f"[{self._stage}] {msg}", *args)
