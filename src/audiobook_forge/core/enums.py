"""Enumerations shared across the domain."""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """Lifecycle states of a conversion task.

    The values are stored verbatim in the JSON queue, so they must stay stable.
    """

    QUEUED = "queued"
    RUNNING = "running"
    RESUMING = "resuming"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Whether no further processing will happen for this state."""
        return self in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class Stage(str, Enum):
    """Named pipeline stages, used for logging and progress reporting."""

    DOWNLOAD = "download"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    SPLIT = "split"
    GENERATE_AUDIO = "generate_audio"
    MERGE = "merge"
    ENCODE = "encode"
    METADATA = "metadata"
    RELEASE = "release"
    CLEANUP = "cleanup"
