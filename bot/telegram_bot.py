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
import asyncio
import base64
import html
import json
import os
import re
import subprocess
import tempfile
import time
import datetime as dt
import secrets

import requests
from telegram import (
    BotCommand,
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

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

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
    r = requests.get(url, headers=GH_HEADERS, params={"ref": GH_BRANCH}, timeout=30)
    if r.status_code == 200:
        data["sha"] = r.json()["sha"]
    resp = requests.put(url, headers=GH_HEADERS, json=data, timeout=60)
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
            "start": str(opts.get("start", "1")),
            "limit": str(opts.get("limit", "0")),
            "batch_size": str(opts.get("batch_size", "0")),
            "install_calibre": str(opts.get("install_calibre", "false")).lower(),
        },
    }
    resp = requests.post(url, headers=GH_HEADERS, json=payload, timeout=30)
    resp.raise_for_status()


def gh_find_run(job_id, since_iso, timeout=60):
    """Tim workflow run vua tao (theo thoi diem)."""
    url = "%s/repos/%s/actions/workflows/%s/runs" % (GH_API, GH_REPO, WORKFLOW_FILE)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, headers=GH_HEADERS, params={"branch": GH_BRANCH, "per_page": 20}, timeout=30)
        if r.status_code == 200:
            for run in r.json().get("workflow_runs", []):
                label = "%s %s" % (run.get("name", ""), run.get("display_title", ""))
                if run["created_at"] >= since_iso and job_id in label:
                    return run["id"]
        time.sleep(3)
    return None


def gh_wait_run(run_id, timeout=3600):
    """Cho workflow run hoan tat. Tra ve conclusion (success/failure/...)."""
    url = "%s/repos/%s/actions/runs/%s" % (GH_API, GH_REPO, run_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, headers=GH_HEADERS, timeout=30)
        if r.status_code == 200:
            run = r.json()
            if run["status"] == "completed":
                return run["conclusion"]
        time.sleep(10)
    return "timed_out"


def gh_get_release(tag):
    url = "%s/repos/%s/releases/tags/%s" % (GH_API, GH_REPO, tag)
    r = requests.get(url, headers=GH_HEADERS, timeout=30)
    if r.status_code == 200:
        return r.json()
    return None


# ------------------------------------------------------------ bot state

# Luu tam trang thai job dang cho chon option, theo chat_id.
PENDING = {}

SPEED_OPTIONS = {
    "speed_0.9": ("\u26a1 Nhanh (0.9)", "0.9"),
    "speed_1.0": ("\U0001f3c3 Chu\u1ea9n (1.0)", "1.0"),
    "speed_1.1": ("\U0001f6b6 Ch\u1eadm (1.1)", "1.1"),
    "speed_1.3": ("\U0001f422 R\u1ea5t ch\u1eadm (1.3)", "1.3"),
}
FORMAT_OPTIONS = {
    "fmt_mp3": ("\U0001f3b5 MP3", "mp3"),
    "fmt_m4b": ("\U0001f4da M4B (audiobook)", "m4b"),
    "fmt_wav": ("\U0001f4bf WAV", "wav"),
}

# Cac muc chon nhanh so chuong (chi hien nhung muc nho hon tong so chuong).
CHAPTER_QUICK = (10, 20, 50, 100)

# Khi chon "Tat ca" (ca bo): moi 20 chuong dong thanh 1 zip rieng roi gui.
BATCH_SIZE_ALL = 20


def _probe_chapters_blocking(content, filename):
    """Best-effort: DEM so chuong bang parse_ebook.py --probe. Loi -> None.

    Ghi tam noi dung ra file de parser doc, chay probe, roi xoa file tam.
    """
    tmp_path = None
    try:
        suffix = os.path.splitext(filename)[1] or ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(content)
            tmp_path = tf.name
        out = subprocess.run(
            ["python3", os.path.join(REPO_ROOT, "pipeline", "parse_ebook.py"),
             "--input", tmp_path, "--probe"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=300,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:  # noqa - probe la best-effort
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def probe_chapters(content, filename):
    """Chay probe trong executor de khong chan vong lap asyncio."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _probe_chapters_blocking, content, filename)


def chapter_keyboard(total):
    rows = []
    for n in CHAPTER_QUICK:
        if n < total:
            rows.append([InlineKeyboardButton(
                "\U0001f4d6 %d ch\u01b0\u01a1ng \u0111\u1ea7u" % n, callback_data="chap_%d" % n)])
    rows.append([InlineKeyboardButton(
        "\U0001f4da T\u1ea5t c\u1ea3 (%d ch\u01b0\u01a1ng)" % total, callback_data="chap_all")])
    return InlineKeyboardMarkup(rows)


def parse_chapter_choice(text, total):
    """Phan tich lua chon so chuong nguoi dung go tay.

    Tra ve (start, limit): start 1-based, limit = so chuong (0 = het). None neu sai.
    """
    t = (text or "").strip().lower()
    if t in ("all", "t\u1ea5t c\u1ea3", "tat ca", "tatca", "h\u1ebft", "het", "0"):
        return (1, 0)
    m = re.match(r"^(\d+)\s*[-\u2013\u2014]\s*(\d+)$", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a >= 1 and b >= a:
            return (a, b - a + 1)
        return None
    if t.isdigit():
        n = int(t)
        if n >= 1:
            return (1, n)
    return None


def allowed(update):
    if not ALLOWED:
        return True
    uid = update.effective_user.id if update.effective_user else None
    return uid in ALLOWED


# ------------------------------------------------------------ handlers

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f44b <b>Ch\u00e0o b\u1ea1n!</b>\n\n"
        "M\u00ecnh l\u00e0 bot chuy\u1ec3n <b>ebook</b> th\u00e0nh <b>audiobook</b> "
        "v\u1edbi gi\u1ecdng \u0111\u1ecdc <b>Ng\u1ecdc Huy\u1ec1n</b>. \U0001f3a7\n\n"
        "\U0001f4d6 G\u1eedi m\u1ed9t file ebook, m\u00ecnh s\u1ebd \u0111\u1ecdc th\u00e0nh file \u00e2m thanh cho b\u1ea1n.\n\n"
        "\u25b6\ufe0f G\u00f5 /tts \u0111\u1ec3 b\u1eaft \u0111\u1ea7u. G\u00f5 /help \u0111\u1ec3 xem h\u01b0\u1edbng d\u1eabn.",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f4da <b>H\u01b0\u1edbng d\u1eabn s\u1eed d\u1ee5ng</b>\n\n"
        "<b>1.</b> G\u00f5 /tts r\u1ed3i g\u1eedi file ebook.\n"
        "<b>2.</b> Ch\u1ecdn <b>s\u1ed1 ch\u01b0\u01a1ng</b> mu\u1ed1n t\u1ea1o (tr\u00e1nh qu\u00e1 t\u1ea3i c\u1ea3 cu\u1ed1n).\n"
        "<b>3.</b> Nh\u1eadp <b>t\u00ean truy\u1ec7n</b> (ho\u1eb7c /skip \u0111\u1ec3 d\u00f9ng t\u00ean file).\n"
        "<b>4.</b> Ch\u1ecdn <b>t\u1ed1c \u0111\u1ed9 \u0111\u1ecdc</b> v\u00e0 <b>\u0111\u1ecbnh d\u1ea1ng</b> audio.\n"
        "<b>5.</b> Ch\u1edd t\u1ea1o xong v\u00e0 nh\u1eadn link t\u1ea3i v\u1ec1. \u2728\n\n"
        "\U0001f4c1 <i>H\u1ed7 tr\u1ee3: .txt, .epub, .pdf, .docx, .zip, .mobi\u2026</i>",
        parse_mode="HTML",
    )


async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("\U0001f6ab B\u1ea1n kh\u00f4ng c\u00f3 quy\u1ec1n s\u1eed d\u1ee5ng bot n\u00e0y.")
        return
    chat_id = update.effective_chat.id
    PENDING[chat_id] = {"step": "await_file"}
    await update.message.reply_text(
        "\U0001f4ce H\u00e3y g\u1eedi (\u0111\u00ednh k\u00e8m) <b>file ebook</b> b\u1ea1n mu\u1ed1n chuy\u1ec3n th\u00e0nh audio.\n\n"
        "<i>H\u1ed7 tr\u1ee3: .txt, .epub, .pdf, .docx, .zip, .mobi\u2026</i>",
        parse_mode="HTML",
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("\U0001f6ab B\u1ea1n kh\u00f4ng c\u00f3 quy\u1ec1n s\u1eed d\u1ee5ng bot n\u00e0y.")
        return
    doc = update.message.document
    name = os.path.basename((doc.file_name or "input.txt").replace("\\", "/"))
    name = re.sub(r"[^\w.() -]", "_", name, flags=re.UNICODE)[:180] or "input.txt"
    ext = os.path.splitext(name)[1].lower()
    if ext not in SUPPORTED_EXT:
        await update.message.reply_text(
            "\u26a0\ufe0f \u0110\u1ecbnh d\u1ea1ng <code>%s</code> ch\u01b0a \u0111\u01b0\u1ee3c h\u1ed7 tr\u1ee3.\n\nH\u00e3y g\u1eedi c\u00e1c \u0111\u1ecbnh d\u1ea1ng: %s"
            % (html.escape(ext), ", ".join(SUPPORTED_EXT)),
            parse_mode="HTML",
        )
        return
    if doc.file_size and doc.file_size > 45 * 1024 * 1024:
        await update.message.reply_text("\u26a0\ufe0f File qu\u00e1 l\u1edbn (>45MB). H\u00e3y chia nh\u1ecf ho\u1eb7c n\u00e9n zip l\u1ea1i.")
        return

    await update.message.reply_text("\U0001f4e5 \u0110\u00e3 nh\u1eadn file, \u0111ang t\u1ea3i v\u1ec1\u2026")
    tg_file = await doc.get_file()
    content = bytes(await tg_file.download_as_bytearray())

    chat_id = update.effective_chat.id
    state = {
        "step": "await_title",
        "filename": name,
        "content": content,
        "title": os.path.splitext(name)[0],
        "length_scale": "1.0",
        "format": "mp3",
        "install_calibre": "true" if ext in (".mobi", ".azw3", ".azw", ".fb2") else "false",
        "start": "1",
        "limit": "0",
        "batch_size": "0",
    }
    PENDING[chat_id] = state
    await update.message.reply_text(
        "\u2705 <b>\u0110\u00e3 nh\u1eadn file:</b> <code>%s</code>\n\n"
        "\U0001f50e \u0110ang ki\u1ec3m tra s\u1ed1 ch\u01b0\u01a1ng\u2026"
        % html.escape(name),
        parse_mode="HTML",
    )
    # Xem truoc so chuong de hoi nguoi dung muon tao bao nhieu (tranh qua tai).
    info = await probe_chapters(content, name)
    total = int(info.get("count", 0)) if info else 0
    if total > 1:
        state["chapters_total"] = total
        await _ask_chapters(update, state)
    else:
        await _ask_title(chat_id, state, context)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    state = PENDING.get(chat_id)
    if not state:
        await query.edit_message_text("\u231b Phi\u00ean \u0111\u00e3 h\u1ebft h\u1ea1n. H\u00e3y g\u1eedi l\u1ea1i file ho\u1eb7c g\u00f5 /tts.")
        return
    data = query.data

    if data in SPEED_OPTIONS:
        state["length_scale"] = SPEED_OPTIONS[data][1]
        state["step"] = "await_format"
        kb = [[InlineKeyboardButton(lbl, callback_data=key)] for key, (lbl, _) in FORMAT_OPTIONS.items()]
        await query.edit_message_text(
            "\u23f1\ufe0f T\u1ed1c \u0111\u1ed9: <b>%s</b>\n\n\U0001f3b5 Gi\u1edd ch\u1ecdn <b>\u0111\u1ecbnh d\u1ea1ng</b> audio:" % SPEED_OPTIONS[data][0],
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )
        return

    if data.startswith("chap_"):
        choice = data[len("chap_"):]
        total = int(state.get("chapters_total", 0))
        if choice == "all":
            state["start"], state["limit"] = "1", "0"
            state["batch_size"] = str(BATCH_SIZE_ALL)
            label = "T\u1ea5t c\u1ea3 (%d ch\u01b0\u01a1ng)" % total
        else:
            state["start"], state["limit"] = "1", choice
            state["batch_size"] = "0"
            label = "%s ch\u01b0\u01a1ng \u0111\u1ea7u" % choice
        await query.edit_message_text(
            "\U0001f4da S\u1ed1 ch\u01b0\u01a1ng: <b>%s</b>" % html.escape(label),
            parse_mode="HTML",
        )
        await _ask_title(chat_id, state, context)
        return

    if data in FORMAT_OPTIONS:
        state["format"] = FORMAT_OPTIONS[data][1]
        await query.edit_message_text(
            "\U0001f3ac <b>Truy\u1ec7n:</b> %s\n"
            "\u23f1\ufe0f T\u1ed1c \u0111\u1ed9: <b>%s</b>  |  \U0001f3b5 \u0110\u1ecbnh d\u1ea1ng: <b>%s</b>\n\n"
            "\u23f3 <b>\u0110ang b\u1eaft \u0111\u1ea7u t\u1ea1o audio\u2026</b> M\u00ecnh s\u1ebd b\u00e1o khi xong nh\u00e9!"
            % (html.escape(state["title"]), state["length_scale"], FORMAT_OPTIONS[data][1]),
            parse_mode="HTML",
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
        "start": state.get("start", "1"),
        "limit": state.get("limit", "0"),
        "batch_size": state.get("batch_size", "0"),
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
        await context.bot.send_message(chat_id, "\u274c L\u1ed7i khi \u0111\u1ea9y l\u00ean GitHub: %s" % html.escape(str(e)))
        return

    await context.bot.send_message(
        chat_id,
        "\u23f3 <b>\u0110ang t\u1ea1o audio cho truy\u1ec7n:</b> %s\n"
        "<i>(\u0111ang ch\u1ea1y tr\u00ean GitHub Actions, c\u00f3 th\u1ec3 m\u1ea5t v\u00e0i ph\u00fat\u2026)</i>"
        % html.escape(state["title"]),
        parse_mode="HTML",
    )

    # 3. Theo doi run.
    run_id = gh_find_run(job_id, since_iso)
    if not run_id:
        await context.bot.send_message(
            chat_id,
            "\u26a0\ufe0f \u0110\u00e3 k\u00edch ho\u1ea1t workflow nh\u01b0ng ch\u01b0a t\u00ecm th\u1ea5y run. H\u00e3y ki\u1ec3m tra tab Actions c\u1ee7a repo.",
        )
        return
    conclusion = gh_wait_run(run_id)

    if conclusion != "success":
        await context.bot.send_message(
            chat_id,
            "\u274c Workflow k\u1ebft th\u00fac v\u1edbi tr\u1ea1ng th\u00e1i: <b>%s</b>. Xem log t\u1ea1i tab Actions." % html.escape(str(conclusion)),
            parse_mode="HTML",
        )
        return

    # 4. Lay Release + gui link.
    tag = "audiobook-%s" % job_id
    rel = gh_get_release(tag)
    if not rel:
        await context.bot.send_message(chat_id, "\u2705 Xong nh\u01b0ng ch\u01b0a th\u1ea5y Release. Th\u1eed l\u1ea1i sau nh\u00e9.")
        return
    assets = rel.get("assets", [])
    title_html = html.escape(state["title"])
    lines = [
        "\U0001f389 <b>Truy\u1ec7n: %s \u0111\u00e3 ho\u00e0n th\u00e0nh!</b>" % title_html,
        "",
        "\U0001f517 <b>Link t\u1ea3i:</b>",
        rel["html_url"],
    ]
    if assets:
        lines.append("")
        lines.append("\U0001f4c1 <b>File:</b>")
    for a in assets:
        size_mb = a.get("size", 0) / (1024 * 1024)
        lines.append("\u2022 <b>%s</b> (%.1f MB)\n%s" % (html.escape(a["name"]), size_mb, a["browser_download_url"]))
    await context.bot.send_message(chat_id, "\n".join(lines), disable_web_page_preview=True, parse_mode="HTML")


async def _ask_chapters(update: Update, state):
    state["step"] = "await_chapters"
    total = int(state.get("chapters_total", 0))
    await update.message.reply_text(
        "\U0001f4da S\u00e1ch n\u00e0y c\u00f3 <b>%d ch\u01b0\u01a1ng</b>.\n\n"
        "G\u1eedi c\u1ea3 cu\u1ed1n m\u1ed9t l\u00fac c\u00f3 th\u1ec3 g\u00e2y <b>qu\u00e1 t\u1ea3i</b>. "
        "B\u1ea1n mu\u1ed1n t\u1ea1o bao nhi\u00eau ch\u01b0\u01a1ng?\n\n"
        "\U0001f449 Ch\u1ecdn nhanh b\u00ean d\u01b0\u1edbi, ho\u1eb7c nh\u1eadp <b>s\u1ed1</b> (vd <code>20</code>) "
        "ho\u1eb7c <b>kho\u1ea3ng ch\u01b0\u01a1ng</b> (vd <code>1-30</code>)." % total,
        reply_markup=chapter_keyboard(total),
        parse_mode="HTML",
    )


async def _ask_title(chat_id, state, context):
    state["step"] = "await_title"
    await context.bot.send_message(
        chat_id,
        "\U0001f4dd <b>T\u00ean truy\u1ec7n</b> l\u00e0 g\u00ec? Nh\u1eadp t\u00ean, ho\u1eb7c g\u00f5 /skip \u0111\u1ec3 d\u00f9ng: <i>%s</i>"
        % html.escape(state.get("title", "")),
        parse_mode="HTML",
    )


async def _ask_speed(update: Update, chat_id, state):
    state["step"] = "await_speed"
    kb = [[InlineKeyboardButton(lbl, callback_data=key)] for key, (lbl, _) in SPEED_OPTIONS.items()]
    await update.message.reply_text(
        "\U0001f3ac <b>Truy\u1ec7n:</b> %s\n\n\u23f1\ufe0f Ch\u1ecdn <b>t\u1ed1c \u0111\u1ed9 \u0111\u1ecdc</b>:" % html.escape(state["title"]),
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = PENDING.get(chat_id)
    if not state or state.get("step") != "await_title":
        return
    await _ask_speed(update, chat_id, state)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhan van ban khi bot dang cho SO CHUONG hoac TEN TRUYEN."""
    chat_id = update.effective_chat.id
    state = PENDING.get(chat_id)
    if not state:
        return
    text = (update.message.text or "").strip()

    if state.get("step") == "await_chapters":
        parsed = parse_chapter_choice(text, state.get("chapters_total", 0))
        if not parsed:
            await update.message.reply_text(
                "\u26a0\ufe0f Ch\u01b0a hi\u1ec3u. H\u00e3y nh\u1eadp m\u1ed9t <b>s\u1ed1</b> (vd <code>20</code>) "
                "ho\u1eb7c m\u1ed9t <b>kho\u1ea3ng</b> (vd <code>1-30</code>), ho\u1eb7c b\u1ea5m n\u00fat b\u00ean tr\u00ean.",
                parse_mode="HTML",
            )
            return
        state["start"], state["limit"] = str(parsed[0]), str(parsed[1])
        state["batch_size"] = str(BATCH_SIZE_ALL) if parsed[1] == 0 else "0"
        await _ask_title(chat_id, state, context)
        return

    if state.get("step") != "await_title":
        return
    if text:
        state["title"] = text
    await _ask_speed(update, chat_id, state)


async def _post_init(app):
    """Dat menu lenh goi y (hien khi go '/')."""
    await app.bot.set_my_commands([
        BotCommand("tts", "\U0001f3a7 T\u1ea1o audiobook t\u1eeb file ebook"),
        BotCommand("skip", "\u23ed\ufe0f B\u1ecf qua \u0111\u1eb7t t\u00ean truy\u1ec7n"),
        BotCommand("help", "\u2753 Xem h\u01b0\u1edbng d\u1eabn"),
        BotCommand("start", "\U0001f44b Gi\u1edbi thi\u1ec7u bot"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("tts", cmd_tts))
    app.add_handler(CommandHandler("skip", cmd_skip))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    print("Bot dang chay...", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
