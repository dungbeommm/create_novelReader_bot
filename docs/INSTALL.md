# Installation & Deployment

Audiobook Forge has two runtime roles:

1. **Bot** — a tiny always-on process (Docker) that talks to Telegram and
   dispatches jobs. Low RAM/CPU; runs anywhere.
2. **Worker** — runs *inside GitHub Actions* on free runners and does the heavy
   TTS/audio work, then publishes a Release and notifies the user.

## 1. Prerequisites

- A GitHub repository (this one, pushed to your account).
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- A GitHub token:
  - Inside Actions, the built-in `GITHUB_TOKEN` is used automatically.
  - For the **bot** to dispatch workflows and upload intake files, create a
    fine-grained PAT with `contents: read/write` and `actions: read/write` on
    this repo.
- Docker + Docker Compose on the host running the bot (optional but recommended).

## 2. Configure secrets

### Repository secrets (Settings → Secrets and variables → Actions)

| Secret | Used by | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | worker (to notify user) | Same token as the bot |

`GITHUB_TOKEN` is provided automatically to the workflow — do not add it.

### Bot host environment (`.env`, never committed)

Copy `.env.example` to `.env` and fill in:

```dotenv
TELEGRAM_BOT_TOKEN=123456:abc...
TELEGRAM_ALLOWED_USER_IDS=11111111,22222222   # optional allowlist
GITHUB_TOKEN=github_pat_...
GITHUB_REPOSITORY=your-user/audiobook-forge
GITHUB_REF=main
```

> **Security:** tokens are read only from the environment / GitHub Secrets.
> They are never written to source, logs, or release assets.

## 3. Add voices

Drop Piper voices into `models/` (see `models/README.md`). The repo already
includes a Vietnamese *Ngọc Huyền* voice under `models/ngoc_huyen/`.

## 4. Run the bot

### With Docker (recommended)

```bash
docker compose up -d --build
docker compose logs -f
```

### Without Docker

```bash
python -m pip install -e .
sudo apt-get install -y ffmpeg espeak-ng          # system deps
export $(grep -v '^#' .env | xargs)               # load env
audiobook-forge bot
```

## 5. Verify

1. Open your bot in Telegram, send `/start`.
2. Upload a small `.txt` or `.epub`.
3. Pick options via the buttons, press **Start conversion**.
4. Watch the Actions run; when it finishes you'll get a Release link.

## 6. Development

```bash
pip install -e ".[dev]"
ruff check src tests
mypy src
pytest -q
```
