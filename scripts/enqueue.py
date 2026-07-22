#!/usr/bin/env python3
"""Developer helper: enqueue a local conversion without Telegram.

Useful for testing the pipeline end-to-end from the command line:

    python scripts/enqueue.py path/to/book.epub --voice ngoc_huyen --format mp3

This simply forwards to the ``convert`` CLI subcommand.
"""

from __future__ import annotations

import sys

from audiobook_forge.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["convert", *sys.argv[1:]]))
