"""Telegram application factory and runner (python-telegram-bot v21)."""

from __future__ import annotations

import os

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from ..config.loader import load_settings
from ..config.models import Settings
from ..github.client import GitHubClient
from ..queue.task_queue import TaskQueue
from ..tts.voices import VoiceScanner
from ..utils.logging import get_logger, setup_logging
from .dispatch import ActionsDispatcher
from .handlers import BotHandlers

logger = get_logger(__name__)


def build_application(settings: Settings | None = None) -> Application:
    """Construct a fully-wired Telegram application.

    Raises:
        RuntimeError: if the bot token is not configured via environment.
    """
    settings = settings or load_settings()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Configure it via environment/secret.")

    client = GitHubClient(
        repository=settings.github.repository,
        api_url=settings.github.api_url,
    )
    dispatcher = ActionsDispatcher(settings, client)
    queue = TaskQueue(settings.queue)
    voices = VoiceScanner(settings.tts.models_dir, settings.tts.default_voice)
    handlers = BotHandlers(settings, dispatcher, queue, voices)

    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.on_document))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))
    return app


def run_bot() -> None:
    """Entrypoint for the long-running bot process (polling mode)."""
    settings = load_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Audiobook Forge Telegram bot")
    app = build_application(settings)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
