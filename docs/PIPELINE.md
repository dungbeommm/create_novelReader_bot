# Conversion Pipeline

The pipeline (`pipelines/conversion.py`) transforms source ebook(s) into a
finished, tagged audiobook. Every stage logs with a consistent stage label and
reports progress to the caller (Telegram/queue).

## Stages

1. **Download** (worker): fetch source files from the transient intake release.
2. **Extract**: detect each file's type, expand archives, and read text.
   - EPUB: read metadata + spine/TOC, keep chapter order, strip HTML/CSS to
     clean text (`ebook/extractors/epub.py`).
   - TXT/MD/HTML/FB2/MOBI/AZW3: decode robustly, convert to plain text; MOBI/
     AZW3 use a Calibre `ebook-convert` fallback when available.
   - Multiple sources / archived `.txt` are merged in natural order.
3. **Chapterize**: for text without structure, detect chapters via multiple
   patterns (Chương 1, Chương I, Chapter, 第1章, Phần, Quyển, Volume, Book, and
   Markdown headings). Never relies on a single regex.
4. **Normalize**: pluggable rule engine (Unicode NFC, whitespace, punctuation,
   brackets, ellipsis, newlines, special chars, HTML entities, emoji, Markdown,
   BBCode) plus the Vietnamese layer (abbreviations, symbols, numbers, dates,
   times, currency, units, `%`, email, URL). Example: `100km` -> `một trăm ki
   lô mét`.
5. **Split (segment)**: break each chapter into TTS-sized segments by paragraph
   then sentence, respecting `soft_chars`/`max_chars`/`max_tokens` and never
   cutting mid-sentence; optional sentence overlap.
6. **Generate audio**: for each segment, compute the SHA256 cache key; on a hit
   reuse the cached WAV, otherwise synthesize with Piper. Synthesis is retried
   on transient errors.
7. **Post-process** (per segment): volume normalize (loudnorm), optional noise
   reduction, silence trimming (`audio/processing.py`).
8. **Merge**: concatenate segment WAVs into a chapter WAV; if the user chose a
   single file, merge all chapters.
9. **Encode**: encode to the chosen format/bitrate/sample rate and embed tags
   (title, album, artist, track, language) plus cover art.
10. **Metadata**: generate/reuse cover, and write `playlist.m3u`,
    `chapter.json`, `metadata.json`.
11. **Release** (worker): package assets (direct upload, or auto-zip at
    >=100 files or when compression is ON) and publish the GitHub Release.
12. **Cleanup** (worker): delete the transient intake release.

## Fault tolerance

- **Cache**: `cache/audio_cache.py` keys audio by
  `SHA256(text + voice + speed + sample_rate + format)`. Identical text is never
  re-rendered.
- **Checkpoint + resume**: after each chapter, `checkpoint/store.py` records the
  completed chapters and encoded files. The pipeline takes a soft `deadline`;
  when exceeded it saves the checkpoint and raises `TimeBudgetExceeded`. The
  worker returns exit code 75 and the workflow re-dispatches to continue.
- **Retry**: `tenacity` guards Piper synthesis and GitHub API calls with
  exponential backoff.

## Performance notes

- Segment-level caching drastically cuts repeated work (series, re-runs).
- WAV intermediates are kept in the run's work dir and cleaned per task.
- ffmpeg filter chains are built once per segment; encoding happens once per
  chapter (or once for single-file mode).
- Designed to stay within GitHub-hosted runner RAM/CPU with modest memory use.
