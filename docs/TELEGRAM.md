# Telegram Bot Guide

The bot is the only interface a user needs. Everything is button-driven with
inline keyboards; there are no arguments to type.

## Sending content

- **Single ebook**: send any supported file (`txt, epub, fb2, mobi, azw3, html,
  xhtml, md`).
- **Archive**: send `zip / 7z / rar`. Archives are expanded; every ebook inside
  is processed. Multiple `.txt` files are merged in natural (numeric-aware) order.
- **Multiple files at once**: send several documents (or an album). They are
  grouped into a single conversion (a short debounce window groups the batch).

## Menus

After files arrive you get the **main menu**:

- **Convert N file(s)** -> opens the options menu.
- **Status** -> active tasks with a progress bar.
- **History** -> your recent finished tasks and their download links.
- **Clear files** -> discard the current selection.

The **options menu** exposes every choice from the spec:

| Option | Values |
| --- | --- |
| Voice | Every voice auto-detected in `models/` |
| Speed | 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5 |
| Format | mp3, wav, opus, m4a, aac |
| Bitrate | 64, 96, 128, 192, 256, 320 |
| Sample rate | 22050, 24000, 44100, 48000 |
| Merge | One file per chapter / Single file |
| Compress | ON / OFF |

Press **Start conversion** to enqueue. The bot uploads your file(s) to a
transient intake release and dispatches the GitHub Actions workflow.

## Tracking a task

Each dispatched task shows **Refresh** and **Cancel** buttons:

- **Refresh** re-reads the task from the queue and redraws the progress bar and
  current stage (download, extract, normalize, split, generate audio, merge,
  encode, metadata, release, cleanup).
- **Cancel** marks a non-finished task cancelled.

When the audiobook is ready you receive a message with the **GitHub Release
download link**. If a run hits the time budget you get a short “still working,
resuming” note and the job continues automatically.

## Access control

Set `TELEGRAM_ALLOWED_USER_IDS` to a comma-separated list to restrict the bot to
yourself or your team. Leave it empty for a public bot.

## Callback data scheme

Buttons use compact `namespace:value` callback data (e.g. `voice:ngoc_huyen`,
`speed:1.1`, `action:start`, `cancel:<task_id>`), routed centrally in
`telegram/handlers.py`.
