# Roadmap

Audiobook Forge is production-ready today. These are optional future
enhancements, ordered roughly by value.

## Near term

- **Parallel chapter rendering** on multi-core runners via a job matrix, with a
  final merge job (bounded to stay within free minutes).
- **Webhook mode** for the bot (instead of long polling) for lower latency and
  easier serverless hosting.
- **Per-user quotas / rate limiting** to keep a public bot within free tier.
- **Resumable uploads** for very large books (chunked intake).

## Medium term

- **Pluggable TTS backends** (XTTS, Coqui, cloud voices) behind the existing
  `TTSEngine` port.
- **Pronunciation dictionaries** and per-book overrides for names/terms.
- **SSML-style controls** (pauses, emphasis) derived from structure.
- **Alternative storage backends** for intake/output (S3-compatible) behind the
  existing release port.
- **Redis/SQS queue backend** implementing the current `TaskQueue` interface for
  multi-worker deployments.

## Long term

- **Web dashboard** for status/history alongside Telegram.
- **Chapter-accurate M4B** output with embedded chapter markers.
- **Multi-language normalization packs** (the Vietnamese layer as the template).
- **Voice cloning workflow** documentation and tooling.

## Contributing

Issues and PRs are welcome. Please run `ruff`, `mypy`, and `pytest` before
submitting. See `ARCHITECTURE.md` for where new code belongs — add adapters
behind the ports in `core/interfaces.py` to keep the domain clean.
