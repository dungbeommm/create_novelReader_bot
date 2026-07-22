"""Command-line interface for Audiobook Forge.

Subcommands:
- ``bot``       : run the long-running Telegram bot (polling).
- ``worker``    : run one conversion job inside GitHub Actions.
- ``convert``   : convert a local ebook without Telegram/GitHub (dev/testing).
- ``voices``    : list discovered Piper voices.

All heavy configuration is loaded from YAML + environment; the CLI only parses
invocation arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config.loader import load_settings
from .core.domain import ConversionOptions
from .services.container import Container
from .utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def _cmd_bot(_: argparse.Namespace) -> int:
    from .telegram.bot import run_bot

    run_bot()
    return 0


def _cmd_worker(args: argparse.Namespace) -> int:
    from .worker.run_job import run_job

    return run_job(
        task_id=args.task_id,
        chat_id=int(args.chat_id),
        intake_tag=args.intake_tag,
        options_json=args.options,
    )


def _cmd_convert(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(settings.log_level)
    container = Container(settings)
    options = ConversionOptions(
        voice_id=args.voice or container.voices.default_voice_id(),
        speed=args.speed,
        audio_format=args.format,
        bitrate=args.bitrate,
        sample_rate=args.sample_rate,
        merge_mode=args.merge,
        compress=args.compress,
    )
    result = container.pipeline.run(
        task_id=args.task_id,
        inputs=[Path(p) for p in args.inputs],
        options=options,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_voices(_: argparse.Namespace) -> int:
    settings = load_settings()
    container = Container(settings)
    voices = container.voices.list_voices()
    if not voices:
        print("No voices found. Add <name>.onnx + <name>.onnx.json under models/.")
        return 1
    for voice in voices:
        print(f"- {voice.id}: {voice.display_name} ({voice.language}, {voice.sample_rate} Hz)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audiobook-forge", description="Ebook -> Audiobook automation.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bot", help="Run the Telegram bot").set_defaults(func=_cmd_bot)
    sub.add_parser("voices", help="List available Piper voices").set_defaults(func=_cmd_voices)

    worker = sub.add_parser("worker", help="Run a single conversion job (CI)")
    worker.add_argument("--task-id", required=True)
    worker.add_argument("--chat-id", required=True)
    worker.add_argument("--intake-tag", required=True)
    worker.add_argument("--options", required=True, help="JSON-encoded ConversionOptions")
    worker.set_defaults(func=_cmd_worker)

    convert = sub.add_parser("convert", help="Convert local ebook file(s)")
    convert.add_argument("inputs", nargs="+", help="Ebook or archive paths")
    convert.add_argument("--task-id", default="local")
    convert.add_argument("--voice", default="")
    convert.add_argument("--speed", type=float, default=1.0)
    convert.add_argument("--format", default="mp3")
    convert.add_argument("--bitrate", type=int, default=128)
    convert.add_argument("--sample-rate", type=int, default=22050)
    convert.add_argument("--merge", choices=["per_chapter", "single"], default="per_chapter")
    convert.add_argument("--compress", action="store_true")
    convert.set_defaults(func=_cmd_convert)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("Command failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
