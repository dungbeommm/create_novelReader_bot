"""Telegram update handlers (commands, uploads, inline callbacks).

All interaction after the initial upload happens through inline keyboards, per
the spec. Handlers are thin: they mutate the session, persist tasks in the
queue, and delegate heavy work to :class:`ActionsDispatcher`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ..config.models import Settings
from ..core.domain import Task
from ..core.enums import TaskStatus
from ..utils.fs import ensure_dir, human_size
from ..utils.logging import get_logger
from . import keyboards as kb
from .dispatch import ActionsDispatcher
from .session import SessionStore

logger = get_logger(__name__)


class BotHandlers:
    """Encapsulates all handler callbacks and their shared dependencies."""

    def __init__(self, settings: Settings, dispatcher: ActionsDispatcher, queue, voices) -> None:
        self._settings = settings
        self._dispatcher = dispatcher
        self._queue = queue
        self._voices = voices
        self._sessions = SessionStore()
        self._intake_dir = ensure_dir(Path(settings.work_dir) / "intake")

    # -- Authorization ------------------------------------------------------
    def _authorized(self, user_id: int) -> bool:
        allowed = self._settings.telegram.allowed_user_ids
        return not allowed or user_id in allowed

    async def _guard(self, update: Update) -> bool:
        user = update.effective_user
        if user and self._authorized(user.id):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("\u26d4 You are not authorized to use this bot.")
        return False

    # -- Commands -----------------------------------------------------------
    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.effective_message.reply_text(
            "\U0001f4d6 *Audiobook Forge*\n\n"
            "Send me an ebook (txt, epub, fb2, mobi, azw3, html, xhtml, md) or an "
            "archive (zip / 7z / rar). You can send several files at once.\n\n"
            "I'll show buttons to pick voice, speed, format and more, then convert "
            "it into an audiobook and send back a download link.",
            parse_mode="Markdown",
        )

    async def help_command(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.effective_message.reply_text(
            "Send an ebook, then use the buttons. Everything is button-driven \u2014 "
            "no commands to memorize. Use the Status and History buttons to track jobs."
        )

    # -- File intake --------------------------------------------------------
    async def on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        message = update.effective_message
        document = message.document
        if document is None:
            return

        max_bytes = self._settings.telegram.max_upload_mb * 1024 * 1024
        if document.file_size and document.file_size > max_bytes:
            await message.reply_text(
                f"\u26a0 File too large ({human_size(document.file_size)}). "
                f"Limit is {self._settings.telegram.max_upload_mb} MB."
            )
            return

        user = update.effective_user
        session = self._sessions.get(message.chat_id, user.id, user.full_name)
        dest = self._intake_dir / f"{message.chat_id}_{document.file_unique_id}_{document.file_name}"
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=str(dest))
        session.add_file(str(dest))
        logger.info("Received %s (%s)", document.file_name, human_size(document.file_size or 0))

        # Debounce albums: wait briefly so multi-file uploads are grouped.
        await asyncio.sleep(self._settings.telegram.media_group_wait_seconds)
        await message.reply_text(
            f"\U0001f4e5 Received *{len(session.files)}* file(s).",
            parse_mode="Markdown",
            reply_markup=kb.main_menu(len(session.files)),
        )

    # -- Callback routing ---------------------------------------------------
    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        namespace, _, value = data.partition(":")
        user = update.effective_user
        session = self._sessions.get(query.message.chat_id, user.id, user.full_name)

        handlers = {
            "menu": self._handle_menu,
            "set": self._handle_set,
            "voice": self._handle_voice,
            "speed": self._handle_speed,
            "format": self._handle_format,
            "bitrate": self._handle_bitrate,
            "samplerate": self._handle_samplerate,
            "merge": self._handle_merge,
            "compress": self._handle_compress,
            "action": self._handle_action,
            "refresh": self._handle_refresh,
            "cancel": self._handle_cancel,
        }
        handler = handlers.get(namespace)
        if handler:
            await handler(update, session, value)

    async def _handle_menu(self, update: Update, session, value: str) -> None:
        query = update.callback_query
        if value == "options":
            await query.edit_message_text("\u2699 Conversion options:", reply_markup=kb.options_menu(session.options))
        elif value == "main":
            await query.edit_message_text(
                f"\U0001f4e5 {len(session.files)} file(s) ready.", reply_markup=kb.main_menu(len(session.files))
            )
        elif value == "clear":
            session.reset()
            await query.edit_message_text("\U0001f5d1 Cleared. Send new files to begin.")
        elif value == "status":
            await self._show_status(update, session)
        elif value == "history":
            await self._show_history(update, session)

    async def _handle_set(self, update: Update, session, value: str) -> None:
        query = update.callback_query
        menus = {
            "voice": ("Choose a voice:", kb.voice_menu(self._voices.list_voices())),
            "speed": ("Choose reading speed:", kb.speed_menu(self._settings)),
            "format": ("Choose output format:", kb.format_menu(self._settings)),
            "bitrate": ("Choose bitrate (kbps):", kb.bitrate_menu(self._settings)),
            "samplerate": ("Choose sample rate (Hz):", kb.samplerate_menu(self._settings)),
            "merge": ("Chapter merge mode:", kb.merge_menu()),
            "compress": ("Compress the result?", kb.compress_menu()),
        }
        if value in menus:
            text, markup = menus[value]
            await query.edit_message_text(text, reply_markup=markup)

    async def _handle_voice(self, update: Update, session, value: str) -> None:
        session.options.voice_id = value
        await self._back_to_options(update, session)

    async def _handle_speed(self, update: Update, session, value: str) -> None:
        session.options.speed = float(value)
        await self._back_to_options(update, session)

    async def _handle_format(self, update: Update, session, value: str) -> None:
        session.options.audio_format = value
        await self._back_to_options(update, session)

    async def _handle_bitrate(self, update: Update, session, value: str) -> None:
        session.options.bitrate = int(value)
        await self._back_to_options(update, session)

    async def _handle_samplerate(self, update: Update, session, value: str) -> None:
        session.options.sample_rate = int(value)
        await self._back_to_options(update, session)

    async def _handle_merge(self, update: Update, session, value: str) -> None:
        session.options.merge_mode = value
        await self._back_to_options(update, session)

    async def _handle_compress(self, update: Update, session, value: str) -> None:
        session.options.compress = value == "on"
        await self._back_to_options(update, session)

    async def _back_to_options(self, update: Update, session) -> None:
        await update.callback_query.edit_message_text(
            "\u2699 Conversion options:", reply_markup=kb.options_menu(session.options)
        )

    async def _handle_action(self, update: Update, session, value: str) -> None:
        query = update.callback_query
        if value != "start":
            return
        if not session.files:
            await query.edit_message_text("\u26a0 No files to convert. Send an ebook first.")
            return
        task = Task(
            user_id=session.user_id,
            chat_id=session.chat_id,
            user_name=session.user_name,
            source_files=list(session.files),
            options=session.options,
        )
        self._queue.enqueue(task)
        await query.edit_message_text(
            f"\U0001f680 Queued task `{task.id}`. Uploading and starting the pipeline\u2026",
            parse_mode="Markdown",
        )
        try:
            await asyncio.to_thread(self._dispatcher.dispatch, task)
            self._queue.update(task)
            await query.message.reply_text(
                f"\u2705 Task `{task.id}` dispatched. You'll get the download link when it's ready.",
                parse_mode="Markdown",
                reply_markup=kb.task_actions(task.id),
            )
        except Exception as exc:  # noqa: BLE001 - surface to user
            task.status = TaskStatus.FAILED
            task.message = str(exc)
            self._queue.update(task)
            logger.exception("Dispatch failed")
            await query.message.reply_text(f"\u274c Failed to dispatch: {exc}")
        finally:
            session.reset()

    async def _handle_refresh(self, update: Update, session, value: str) -> None:
        task = self._queue.get(value)
        if not task:
            await update.callback_query.edit_message_text("Task not found.")
            return
        await update.callback_query.edit_message_text(
            self._format_task(task), parse_mode="Markdown", reply_markup=kb.task_actions(task.id)
        )

    async def _handle_cancel(self, update: Update, session, value: str) -> None:
        ok = self._queue.cancel(value)
        msg = "\U0001f6d1 Task cancelled." if ok else "Task cannot be cancelled (already finished)."
        await update.callback_query.edit_message_text(msg)

    # -- Status / history ---------------------------------------------------
    async def _show_status(self, update: Update, session) -> None:
        tasks = [t for t in self._queue.list_tasks(session.user_id) if not t.status.is_terminal]
        if not tasks:
            await update.callback_query.edit_message_text("No active tasks.")
            return
        text = "\n\n".join(self._format_task(t) for t in tasks[-5:])
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")

    async def _show_history(self, update: Update, session) -> None:
        tasks = [t for t in self._queue.list_tasks(session.user_id) if t.status.is_terminal]
        if not tasks:
            await update.callback_query.edit_message_text("No history yet.")
            return
        lines = [self._format_task(t) for t in tasks[-10:]]
        await update.callback_query.edit_message_text("\n\n".join(lines), parse_mode="Markdown")

    @staticmethod
    def _format_task(task: Task) -> str:
        bar_len = 10
        filled = int(task.progress * bar_len)
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
        line = (
            f"*Task* `{task.id}`\n"
            f"Status: {task.status.value}\n"
            f"Stage: {task.stage or '-'}\n"
            f"Progress: {bar} {int(task.progress * 100)}%"
        )
        if task.release_url:
            line += f"\n[\u2b07 Download]({task.release_url})"
        if task.message:
            line += f"\n_{task.message}_"
        return line
