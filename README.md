# Audiobook Forge

Turn ebooks into narrated audiobooks **fully automatically** from Telegram, using
free GitHub Actions runners for the heavy lifting and [Piper](https://github.com/rhasspy/piper)
for natural neural text-to-speech.

```
User -> Telegram Bot -> GitHub Repo -> GitHub Actions -> Ebook processing
     -> Piper TTS -> Audiobook -> GitHub Release -> Telegram download link
```

Send an ebook to the bot, pick a voice/speed/format with inline buttons, and get
back a GitHub Release download link when it's done. No servers to babysit; the
always-on bot is tiny and every conversion runs on GitHub's free compute.

## Highlights

- **Telegram-first UX** — 100% inline-keyboard driven: voice, speed (0.7–1.5),
  format (mp3/wav/opus/m4a/aac), bitrate, sample rate, per-chapter vs single
  file, and result compression. Status, progress, cancel and history included.
- **Broad input support** — `txt, epub, fb2, mobi, azw3, html, xhtml, md` plus
  `zip / 7z / rar` archives (multi-ebook archives processed in full; multiple
  `.txt` merged in order).
- **Smart chapterization** — EPUB TOC/metadata, and multi-pattern TXT chapter
  detection (Chương 1, Chương I, Chapter, 第1章, Phần, Quyển, Volume, Book…).
- **Text normalization** — pluggable rule engine (Unicode NFC, whitespace,
  punctuation, HTML entities, emoji, Markdown, BBCode…) plus a Vietnamese layer
  that reads numbers, dates, times, currency, units, `%`, email and URLs aloud
  naturally (e.g. `100km` → “một trăm ki lô mét”).
- **Robust audio pipeline** — segment → Piper → volume normalize → optional
  noise reduction → silence trimming → chapter merge → encode → tagged output
  with cover art, `playlist.m3u`, `chapter.json`, `metadata.json`.
- **Fault tolerant** — SHA256 audio cache (never re-render identical text),
  per-chapter checkpoints, automatic **resume** across runner timeouts, and
  retries on transient failures.
- **Free-tier friendly** — dependency + audio caching, self-re-dispatch to stay
  under the 6h cap, artifact uploads, and automatic release packaging
  (direct upload, or auto-zip at ≥100 files).
- **Clean Architecture** — separated `core / services / pipelines / telegram /
  github / tts / ebook / audio / release / config / utils` with full type hints,
  docstrings, unit + integration tests.

## Quick start

1. **Add the bot token & a GitHub token** as secrets (see `INSTALL.md`).
2. **Add voices** to `models/` (a Vietnamese *Ngọc Huyền* voice is bundled).
3. **Run the bot** with Docker: `docker compose up -d`.
4. **Send an ebook** to your bot on Telegram and follow the buttons.

See the full guides:

| Doc | Purpose |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | Setup, secrets, deployment |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit together |
| [docs/CONFIG.md](docs/CONFIG.md) | Every configuration key |
| [docs/TELEGRAM.md](docs/TELEGRAM.md) | Bot interactions & menus |
| [docs/PIPELINE.md](docs/PIPELINE.md) | Conversion stages in detail |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned improvements |

## Local conversion (no Telegram)

```bash
pip install -e .
audiobook-forge voices                      # list detected Piper voices
audiobook-forge convert book.epub --voice ngoc_huyen --format mp3 --merge single
```

## License

MIT — see `LICENSE`. Contributions welcome; this is designed to be a public,
community-maintained open-source project.
