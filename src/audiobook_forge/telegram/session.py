"""Per-chat session state for the option wizard and pending uploads."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..core.domain import ConversionOptions


@dataclass(slots=True)
class Session:
    """Transient state while a user configures and submits a conversion.

    A session accumulates uploaded files (supporting multi-file albums) and the
    in-progress option selections before a task is enqueued.
    """

    chat_id: int
    user_id: int
    user_name: str = ""
    files: list[str] = field(default_factory=list)
    options: ConversionOptions = field(default_factory=ConversionOptions)
    last_activity: float = field(default_factory=time.time)
    media_group_id: str | None = None

    def add_file(self, path: str) -> None:
        if path not in self.files:
            self.files.append(path)
        self.last_activity = time.time()

    def reset(self) -> None:
        self.files.clear()
        self.options = ConversionOptions()
        self.media_group_id = None


class SessionStore:
    """In-memory session registry keyed by chat id."""

    def __init__(self) -> None:
        self._sessions: dict[int, Session] = {}

    def get(self, chat_id: int, user_id: int, user_name: str = "") -> Session:
        session = self._sessions.get(chat_id)
        if session is None:
            session = Session(chat_id=chat_id, user_id=user_id, user_name=user_name)
            self._sessions[chat_id] = session
        return session

    def clear(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)
