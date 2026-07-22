"""Bot Telegram: nhan file ebook -> day len GitHub -> kich hoat workflow
-> theo doi -> gui link GitHub Release.

Cau hinh qua bien moi truong (xem .env.example):
  TELEGRAM_BOT_TOKEN   token cua bot Telegram (@BotFather)
  GITHUB_TOKEN         fine-grained PAT, quyen: Contents (RW) + Actions (RW)
  GITHUB_REPO          dang "owner/repo"  (vd: dungtran/piper-tts-service)
  GITHUB_BRANCH        nhanh muc tieu (mac dinh: main)
  ALLOWED_USER_IDS     (tuy chon) danh sach user id duoc phep, ngan cach dau phay

Chay:
  pip install -r bot/requirements-bot.txt
  python bot/telegram_bot.py

Yeu cau: python-telegram-bot v20+, requests.
"""
import base64
import json
import os
import time
import datetime as dt
import secrets

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ------------------------------------------------------------ config

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_REPO = os.environ["GITHUB_REPO"]          # "owner/repo"
GH_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
WORKFLOW_FILE = os.environ.get("WORKFLOW_FILE", "audiobook.yml")
ALLOWED = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
}

GH_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": "Bearer %s" % GH_TOKEN,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

SUPPORTED_EXT = (
    ".txt", ".epub", ".zip", ".mobi", ".azw3", ".azw",
    ".fb2", ".html", ".htm", ".docx", ".pdf", ".rtf",
)

# ------------------------------------------------------------ github helpers

def gh_put_file(path, content_bytes, message):
    """Tao/ghi de mot file trong repo qua Contents API."""
    url = "%s/repos/%s/contents/%s" % (GH_API, GH_REPO, path)
    data = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": GH_BRANCH,
    }
    # Neu file da ton tai -> can sha de ghi de.
    r = requests.get(url, headers=GH_HEADERS, params={"ref": GH_BRANCH})
    if r.status_code == 200:
        data["sha"] = r.json()["sha"]
    resp = requests.put(url, headers=GH_HEADERS, json=data)
    resp.raise_for_status()
    return resp.json()


def gh_dispatch_workflow(job_id, opts):
    """Kich hoat workflow_dispatch voi input."""
    url = "%s/repos/%s/actions/workflows/%s/dispatches" % (GH_API, GH_REPO, WORKFLOW_FILE)
    payload = {
        "ref": GH_BRANCH,
        "inputs": {
            "job_id": job_id,
            "title": str(opts.get("title", "")),
            "format": str(opts.get("format", "mp3")),
            "length_scale": str(opts.get("length_scale", "1.0")),
            "package": str(opts.get("package", "auto")),
            "max_chars": str(opts.get("max_chars", "0")),
            "install_calibre": str(opts.get("install_calibre", "false")).lower(),
        },
    }
    resp = requests.post(url, headers=GH_HEADERS, json=payload)
    resp.raise_for_status()


def gh_find_run(job_id, since_iso, timeout=60):
    """Tim workflow run vua tao (theo thoi diem)."""
    url = "%s/repos/%s/actions/workflows/%s/runs" % (GH_API, GH_REPO, WORKFLOW_FILE)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, headers=GH_HEADERS, params={"branch": GH_BRANCH, "per_page": 10})
        if r.status_code == 200:
            for run in r.json().get("workflow_runs", []):
                if run["created_at"] >= since_iso:
                    return run["id"]
        time.sleep(3)
    return None


def gh_wait_run(run_id, timeout=3600):
    """Cho workflow run hoan tat. Tra ve conclusion (success/failure/...)."""
    url = "%s/repos/%s/actions/runs/%s" % (GH_API, GH_REPO, run_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, headers=GH_HEADERS)
        if r.status_code == 200:
            run = r.json()
            if run["status"] == "completed":
                return run["conclusion"]
        time.sleep(10)
    return "timed_out"


def gh_get_release(tag):
    url = "%s/repos/%s/releases/tags/%s" % (GH_API, GH_REPO, tag)
    r = requests.get(url, headers=GH_HEADERS)
    if r.status_code == 200:
        return r.json()
    return None


# ------------------------------------------------------------ bot state

# Luu tam trang thai job dang cho chon option, theo chat_id.
PENDING = {}

SPEED_OPTIONS = {
    "speed_0.9": ("Nhanh (0.9)", "0.9"),
    "speed_1.0": ("Chuan (1.0)", "1.0"),
    "speed_1.1": ("Cham (1.1)", "1.1"),
    "speed_1.3": ("Rat cham (1.3)", "1.3"),
}
FORMAT_OPTIONS = {
    "fmt_mp3": ("MP3", "mp3"),
    "fmt_m4b": ("M4B (audiobook)", "m4b"),
    "fmt_wav": ("WAV", "wav"),
}


def allowed(update):
    if not ALLOWED:
        return True
    uid = update.effective_user.id if update.effective_user else None
    return uid in ALLOWED


# ------------------------------------------------------------ handlers

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Xin chao! Gui cho toi mot file ebook (.txt, .epub, .zip chua txt, "
        ".mobi, .pdf, .docx...) va toi se tao audiobook giong Ngoc Huyen.\n\n"
        "Sau khi gui file, ban se chon toc do doc va dinh dang audio. "
        "Khi xong toi gui link tai tren GitHub Release.\n\n"
        "Lenh: /help de xem huong dan."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cach dung:\n"
        "1. Gui file ebook (dinh kem document).\n"
        "2. Chon toc do doc.\n"
        "3. Chon dinh dang audio (MP3 / M4B / WAV).\n"
        "4. Cho vai phut, toi gui link GitHub Release.\n\n"
        "Ho tro: .txt, .epub, .zip(txt), .mobi, .azw3, .fb2, .docx, .pdf, .html"
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("Ban khong co quyen dung bot nay.")
        return
    doc = update.message.document
    name = doc.file_name or "input.txt"
    ext = os.path.splitext(name)[1].lower()
    if ext not in SUPPORTED_EXT:
        await update.message.reply_text(
            "Dinh dang %r chua ho tro. Hay gui: %s" % (ext, ", ".join(SUPPORTED_EXT))
        )
        return
    if doc.file_size and doc.file_size > 45 * 1024 * 1024:
        await update.message.reply_text("File qua lon (>45MB). Hay chia nho hoac nen zip.")
        return

    await update.message.reply_text("Da nhan file, dang tai ve...")
    tg_file = await doc.get_file()
    content = bytes(await tg_file.download_as_bytearray())

    chat_id = update.effective_chat.id
    PENDING[chat_id] = {
        "filename": name,
        "content": content,
        "title": os.path.splitext(name)[0],
        "length_scale": "1.0",
        "format": "mp3",
        "install_calibre": "true" if ext in (".mobi", ".azw3", ".azw", ".fb2") else "false",
    }

    kb = [[InlineKeyboardButton(lbl, callback_data=key)] for key, (lbl, _) in SPEED_OPTIONS.items()]
    await update.message.reply_text(
        "Chon toc do doc:", reply_markup=InlineKeyboardMarkup(kb)
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    state = PENDING.get(chat_id)
    if not state:
        await query.edit_message_text("Phien da het han. Hay gui lai file.")
        return
    data = query.data

    if data in SPEED_OPTIONS:
        state["length_scale"] = SPEED_OPTIONS[data][1]
        kb = [[InlineKeyboardButton(lbl, callback_data=key)] for key, (lbl, _) in FORMAT_OPTIONS.items()]
        await query.edit_message_text(
            "Toc do: %s. Gio chon dinh dang audio:" % SPEED_OPTIONS[data][0],
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    if data in FORMAT_OPTIONS:
        state["format"] = FORMAT_OPTIONS[data][1]
        await query.edit_message_text(
            "Dinh dang: %s. Dang day file len GitHub va bat dau xu ly..."
            % FORMAT_OPTIONS[data][0]
        )
        await run_job(chat_id, state, context)
        PENDING.pop(chat_id, None)
        return


async def run_job(chat_id, state, context):
    """Day file + job.json len GitHub, dispatch workflow, cho ket qua."""
    job_id = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    job_dir = "jobs/%s" % job_id
    since_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    opts = {
        "title": state["title"],
        "format": state["format"],
        "length_scale": state["length_scale"],
        "package": "auto",
        "max_chars": "0",
        "install_calibre": state["install_calibre"],
    }

    try:
        # 1. Upload file ebook + job.json.
        gh_put_file(
            "%s/%s" % (job_dir, state["filename"]),
            state["content"],
            "job %s: them ebook" % job_id,
        )
        gh_put_file(
            "%s/job.json" % job_dir,
            json.dumps(opts, ensure_ascii=False).encode("utf-8"),
            "job %s: them job.json" % job_id,
        )
        # 2. Dispatch workflow.
        gh_dispatch_workflow(job_id, opts)
    except requests.HTTPError as e:
        await context.bot.send_message(chat_id, "Loi khi day len GitHub: %s" % e)
        return

    await context.bot.send_message(
        chat_id,
        "Da tao job `%s` va kich hoat GitHub Actions.\nDang cho tao audio (co the vai phut)..."
        % job_id,
        parse_mode="Markdown",
    )

    # 3. Theo doi run.
    run_id = gh_find_run(job_id, since_iso)
    if not run_id:
        await context.bot.send_message(
            chat_id,
            "Da kich hoat workflow nhung chua tim thay run. Kiem tra tab Actions cua repo.",
        )
        return
    conclusion = gh_wait_run(run_id)

    if conclusion != "success":
        await context.bot.send_message(
            chat_id,
            "Workflow ket thuc voi trang thai: %s. Xem log tai Actions." % conclusion,
        )
        return

    # 4. Lay Release + gui link.
    tag = "audiobook-%s" % job_id
    rel = gh_get_release(tag)
    if not rel:
        await context.bot.send_message(chat_id, "Xong nhung chua thay Release. Thu lai sau.")
        return
    assets = rel.get("assets", [])
    lines = ["Hoan tat! Audiobook cua ban:", rel["html_url"], ""]
    for a in assets:
        size_mb = a.get("size", 0) / (1024 * 1024)
        lines.append("- %s (%.1f MB): %s" % (a["name"], size_mb, a["browser_download_url"]))
    await context.bot.send_message(chat_id, "\n".join(lines), disable_web_page_preview=True)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(CallbackQueryHandler(on_callback))
    print("Bot dang chay...", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
