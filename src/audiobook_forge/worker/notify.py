"""Minimal Telegram notifier used by the Actions worker.

The worker is short-lived and has no bot event loop, so it posts messages
directly via the Bot API using the token from the environment/secret.
"""

from __future__ import annotations

import httpx

from ..utils.logging import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """Sends a plain-text message to a chat via the Telegram Bot API."""

    def __init__(self, token: str, chat_id: int, api_url: str = "https://api.telegram.org") -> None:
        self._token = token
        self._chat_id = chat_id
        self._api = api_url.rstrip("/")

    def send(self, text: str) -> None:
        if not self._token or not self._chat_id:
            logger.warning("Telegram notifier not configured; skipping message.")
            return
        try:
            response = httpx.post(
                f"{self._api}/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text, "disable_web_page_preview": False},
                timeout=30.0,
            )
            if response.status_code != 200:
                logger.warning("Telegram notify failed: %s %s", response.status_code, response.text)
        except httpx.HTTPError as exc:  # pragma: no cover - network
            logger.warning("Telegram notify error: %s", exc)
