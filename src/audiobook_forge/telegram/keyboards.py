"""Inline keyboard builders.

Every user choice is a button; there are no slash-command arguments to type.
Callback data uses a compact ``namespace:value`` scheme parsed by the handlers.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..config.models import Settings
from ..core.domain import ConversionOptions, Voice


def _grid(buttons: list[InlineKeyboardButton], columns: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + columns] for i in range(0, len(buttons), columns)]


def main_menu(file_count: int) -> InlineKeyboardMarkup:
    """Root menu shown after files are received."""
    rows = [
        [InlineKeyboardButton(f"\U0001f3a7 Convert {file_count} file(s)", callback_data="menu:options")],
        [
            InlineKeyboardButton("\U0001f4dc Status", callback_data="menu:status"),
            InlineKeyboardButton("\U0001f552 History", callback_data="menu:history"),
        ],
        [InlineKeyboardButton("\u274c Clear files", callback_data="menu:clear")],
    ]
    return InlineKeyboardMarkup(rows)


def options_menu(options: ConversionOptions) -> InlineKeyboardMarkup:
    """Summary menu with one row per configurable option."""
    rows = [
        [InlineKeyboardButton(f"\U0001f5e3 Voice: {options.voice_id or 'auto'}", callback_data="set:voice")],
        [InlineKeyboardButton(f"\u23e9 Speed: {options.speed}", callback_data="set:speed")],
        [InlineKeyboardButton(f"\U0001f3b5 Format: {options.audio_format}", callback_data="set:format")],
        [InlineKeyboardButton(f"\U0001f4c8 Bitrate: {options.bitrate} kbps", callback_data="set:bitrate")],
        [InlineKeyboardButton(f"\U0001f4c9 Sample rate: {options.sample_rate} Hz", callback_data="set:samplerate")],
        [InlineKeyboardButton(f"\U0001f4da Merge: {options.merge_mode}", callback_data="set:merge")],
        [InlineKeyboardButton(f"\U0001f5dc Compress: {'ON' if options.compress else 'OFF'}", callback_data="set:compress")],
        [InlineKeyboardButton("\u2705 Start conversion", callback_data="action:start")],
        [InlineKeyboardButton("\u2b05 Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def voice_menu(voices: list[Voice]) -> InlineKeyboardMarkup:
    """Menu listing every discovered Piper voice."""
    buttons = [InlineKeyboardButton(v.display_name, callback_data=f"voice:{v.id}") for v in voices]
    rows = _grid(buttons, 2) or [[InlineKeyboardButton("(no voices found)", callback_data="noop")]]
    rows.append([InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")])
    return InlineKeyboardMarkup(rows)


def speed_menu(settings: Settings) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(str(s), callback_data=f"speed:{s}") for s in settings.tts.allowed_speeds
    ]
    rows = _grid(buttons, 4)
    rows.append([InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")])
    return InlineKeyboardMarkup(rows)


def format_menu(settings: Settings) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(fmt, callback_data=f"format:{fmt}") for fmt in settings.audio.allowed_formats
    ]
    rows = _grid(buttons, 3)
    rows.append([InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")])
    return InlineKeyboardMarkup(rows)


def bitrate_menu(settings: Settings) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(str(b), callback_data=f"bitrate:{b}") for b in settings.audio.allowed_bitrates
    ]
    rows = _grid(buttons, 3)
    rows.append([InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")])
    return InlineKeyboardMarkup(rows)


def samplerate_menu(settings: Settings) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(str(sr), callback_data=f"samplerate:{sr}")
        for sr in settings.audio.allowed_sample_rates
    ]
    rows = _grid(buttons, 2)
    rows.append([InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")])
    return InlineKeyboardMarkup(rows)


def merge_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("One file per chapter", callback_data="merge:per_chapter")],
        [InlineKeyboardButton("Single file", callback_data="merge:single")],
        [InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")],
    ]
    return InlineKeyboardMarkup(rows)


def compress_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("ON", callback_data="compress:on"),
            InlineKeyboardButton("OFF", callback_data="compress:off"),
        ],
        [InlineKeyboardButton("\u2b05 Back", callback_data="menu:options")],
    ]
    return InlineKeyboardMarkup(rows)


def task_actions(task_id: str) -> InlineKeyboardMarkup:
    """Actions available for a running/queued task."""
    rows = [
        [
            InlineKeyboardButton("\U0001f504 Refresh", callback_data=f"refresh:{task_id}"),
            InlineKeyboardButton("\U0001f6d1 Cancel", callback_data=f"cancel:{task_id}"),
        ]
    ]
    return InlineKeyboardMarkup(rows)
