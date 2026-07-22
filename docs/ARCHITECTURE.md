# Architecture

Audiobook Forge follows Clean Architecture: business rules live in `core` and
`pipelines`, and all I/O concerns (Telegram, GitHub, Piper, ffmpeg, filesystem)
are adapters wired together by a small composition root.

## High-level flow

```
            Telegram (bot process, always-on, tiny)
                     |  upload ebook + pick options (inline buttons)
                     v
   Upload sources to a transient "intake" GitHub Release
                     |  workflow_dispatch(task_id, chat_id, options, intake_tag)
                     v
        GitHub Actions runner (free compute, heavy work)
   download intake -> pipeline -> package -> GitHub Release
                     |  Bot API sendMessage(chat_id, release_url)
                     v
            Telegram user receives the download link
```

Splitting “always-on” from “heavy compute” keeps hosting cost near zero: the bot
needs almost no resources, and conversions run on GitHub's free runners.

## Layers & packages

| Layer | Package | Responsibility |
| --- | --- | --- |
| Domain | `core` | Entities (`Task`, `Book`, `Chapter`, `Segment`, `ConversionOptions`), enums, errors, and ports (`interfaces.py`). No I/O. |
| Use cases | `pipelines` | `ConversionPipeline` orchestrates the stages using ports. |
| Adapters | `ebook`, `normalize`, `segment`, `tts`, `audio`, `metadata`, `cache`, `checkpoint`, `queue`, `github`, `release`, `telegram`, `worker` | Concrete implementations of the ports and external integrations. |
| Config | `config` | Pydantic settings + YAML/env loader. |
| Cross-cutting | `utils` | Logging, hashing, filesystem, timing. |
| Composition | `services.Container` | Builds and memoizes the object graph. |

## Key design decisions

- **Ports & adapters.** `core/interfaces.py` defines `Protocol`s (e.g.
  `TTSEngine`, `ReleasePublisher`, `ProgressReporter`). The pipeline depends on
  these, not concrete classes, so swapping Piper for another engine, or GitHub
  Releases for S3, is a one-line change in the container.
- **Content-addressed cache.** Each segment's cache key is
  `SHA256(normalized_text + voice + speed + sample_rate + format)`. Identical
  text is synthesized once, ever — across chapters, tasks and runs.
- **Checkpoint + resume.** Progress is written after each chapter. The pipeline
  accepts a soft `deadline`; when exceeded it saves the checkpoint and raises
  `TimeBudgetExceeded`. The worker exits with code 75 and the workflow
  re-dispatches itself to continue — never restarting.
- **Durable queue.** `queue.TaskQueue` persists each `Task` as JSON with a
  lightweight lock, giving history/status/cancel with no external services. The
  narrow interface allows a Redis/SQS backend later.
- **Stateless worker.** The runner reconstructs everything from the dispatch
  inputs + intake release + restored cache, so any runner can pick up a task.

## Data & storage

- **Intake release** (`inbox-<task_id>`, prerelease): temporary object storage
  for uploaded ebooks; deleted during cleanup.
- **Output release** (`audiobook-<task_id>`): final audiobook, metadata,
  playlist, cover and log. Auto-zips audio when ≥ `zip_threshold` files or when
  the user requests compression.
- **Actions cache**: `~/.cache/pip`, `.cache/audio`, `.queue/checkpoints`,
  `.out` — enabling fast, resumable runs.

## Module dependency direction

`telegram` / `worker` → `services` → `pipelines` → `core` ← adapters.
Nothing in `core` imports an adapter, keeping the domain pure and testable.
