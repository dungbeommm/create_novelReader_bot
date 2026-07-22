"""Bot Telegram chay TRONG GitHub Actions (che do poll theo lich).

Khac voi telegram_bot.py (chay lien tuc tren may/VPS), file nay chay theo dot:
moi lan GitHub Actions kich hoat (cron ~5 phut/lan), no se:
  1. Poll tin nhan moi tu Telegram (getUpdates + offset luu trong repo).
  2. Dan dat hoi thoai: /tts -> gui file -> hoi ten truyen -> chon toc do/dinh dang.
  3. Voi job da du thong tin ("ready"): chay parse_ebook + batch_tts NGAY trong
     cung lan chay nay, tao GitHub Release, roi nhan tin bao hoan thanh + link.

Uu diem: KHONG can GitHub token ca nhan (PAT). Trong Actions da co san
GITHUB_TOKEN de tao Release. Chi can 1 secret: TELEGRAM_BOT_TOKEN.

Han che (do dac thu GitHub Actions):
  - Do tre moi buoc hoi thoai ~ chu ky cron (toi da vai phut/lan tra loi).
  - Bot API Telegram chi cho tai file <= 20MB. Ebook lon hon can dung bot VPS.

Trang thai (offset + phien hoi thoai) luu tai bot/state/state.json va file
upload tam tai bot/state/uploads/. Workflow se commit lai sau moi lan chay.
"""
import datetime as dt
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

import requests

# ------------------------------------------------------------ config / env

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_API = "https://api.telegram.org/bot%s" % TG_TOKEN
TG_FILE = "https://api.telegram.org/file/bot%s" % TG_TOKEN

GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo" (Actions tu dat)
GH_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
WORKFLOW_FILE = os.environ.get("WORKFLOW_FILE", "audiobook.yml")
GH_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": "Bearer %s" % GH_TOKEN,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ALLOWED = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
}

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DIR = os.path.join(REPO_ROOT, "bot", "state")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
UPLOAD_DIR = os.path.join(STATE_DIR, "uploads")
WORK_DIR = os.path.join(STATE_DIR, "work")
PY = sys.executable or "python3"

SUPPORTED_EXT = (
    ".txt", ".epub", ".zip", ".mobi", ".azw3", ".azw",
    ".fb2", ".html", ".htm", ".docx", ".pdf", ".rtf",
)
CALIBRE_EXT = {".mobi", ".azw3", ".azw", ".fb2", ".lit", ".pdb"}

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


def probe_chapters(path):
    """Chay parse_ebook.py --probe de DEM so chuong. Loi -> None (bo qua hoi)."""
    try:
        out = subprocess.run(
            [PY, os.path.join(REPO_ROOT, "pipeline", "parse_ebook.py"),
             "--input", path, "--probe"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=300,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:  # noqa - probe la best-effort, that bai thi bo qua
        return None


def chapter_keyboard(total):
    rows = []
    for n in CHAPTER_QUICK:
        if n < total:
            rows.append([{"text": "\U0001f4d6 %d ch\u01b0\u01a1ng \u0111\u1ea7u" % n,
                          "callback_data": "chap_%d" % n}])
    rows.append([{"text": "\U0001f4da T\u1ea5t c\u1ea3 (%d ch\u01b0\u01a1ng)" % total,
                  "callback_data": "chap_all"}])
    return {"inline_keyboard": rows}


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


# ------------------------------------------------------------ telegram api

def tg(method, **params):
    r = requests.post("%s/%s" % (TG_API, method), json=params, timeout=60)
    try:
        return r.json()
    except ValueError:
        return {"ok": False}


def send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg("sendMessage", **params)


def edit(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg("editMessageText", **params)


def set_commands():
    """Dat menu lenh goi y (hien khi go '/') cho dep va tien."""
    tg("setMyCommands", commands=[
        {"command": "tts", "description": "\U0001f3a7 T\u1ea1o audiobook t\u1eeb file ebook"},
        {"command": "skip", "description": "\u23ed\ufe0f B\u1ecf qua \u0111\u1eb7t t\u00ean truy\u1ec7n"},
        {"command": "help", "description": "\u2753 Xem h\u01b0\u1edbng d\u1eabn"},
        {"command": "start", "description": "\U0001f44b Gi\u1edbi thi\u1ec7u bot"},
    ])


def answer_cb(cb_id):
    tg("answerCallbackQuery", callback_query_id=cb_id)


def kb(options):
    return {"inline_keyboard": [[{"text": lbl, "callback_data": key}] for key, (lbl, _) in options.items()]}


def download_tg_file(file_id, dest_path):
    info = tg("getFile", file_id=file_id)
    if not info.get("ok"):
        raise RuntimeError("getFile that bai: %s" % info)
    fp = info["result"]["file_path"]
    r = requests.get("%s/%s" % (TG_FILE, fp), timeout=180)
    r.raise_for_status()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(r.content)


# ------------------------------------------------------------ state

def load_state():
    if os.path.isfile(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"offset": 0, "sessions": {}}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def allowed(user_id):
    return (not ALLOWED) or (user_id in ALLOWED)


# ------------------------------------------------------------ github release

def create_release_with_assets(tag, name, body, files):
    base = "%s/repos/%s" % (GH_API, GH_REPO)
    r = requests.post(
        base + "/releases",
        headers=GH_HEADERS,
        json={"tag_name": tag, "name": name, "body": body[:5000]},
        timeout=60,
    )
    if r.status_code not in (200, 201):
        r = requests.get(base + "/releases/tags/" + tag, headers=GH_HEADERS, timeout=30)
    r.raise_for_status()
    rel = r.json()
    upload_url = rel.get("upload_url", "").split("{")[0]
    for fp in files:
        with open(fp, "rb") as f:
            data = f.read()
        uh = dict(GH_HEADERS)
        uh["Content-Type"] = "application/octet-stream"
        upload = requests.post(upload_url, headers=uh,
                               params={"name": os.path.basename(fp)}, data=data,
                               timeout=300)
        upload.raise_for_status()
    # Lay lai release de co danh sach assets day du.
    r2 = requests.get(base + "/releases/tags/" + tag, headers=GH_HEADERS, timeout=30)
    return r2.json() if r2.status_code == 200 else rel


# ------------------------------------------------------------ handlers

START_TEXT = (
    "\U0001f44b <b>Ch\u00e0o b\u1ea1n!</b>\n\n"
    "M\u00ecnh l\u00e0 bot chuy\u1ec3n <b>ebook</b> th\u00e0nh <b>audiobook</b> "
    "v\u1edbi gi\u1ecdng \u0111\u1ecdc <b>Ng\u1ecdc Huy\u1ec1n</b>. \U0001f3a7\n\n"
    "\U0001f4d6 G\u1eedi m\u1ed9t file ebook, m\u00ecnh s\u1ebd \u0111\u1ecdc th\u00e0nh file \u00e2m thanh cho b\u1ea1n.\n\n"
    "\u25b6\ufe0f G\u00f5 /tts \u0111\u1ec3 b\u1eaft \u0111\u1ea7u."
)
HELP_TEXT = (
    "\U0001f4da <b>H\u01b0\u1edbng d\u1eabn s\u1eed d\u1ee5ng</b>\n\n"
    "<b>1.</b> G\u00f5 /tts r\u1ed3i g\u1eedi file ebook.\n"
    "<b>2.</b> Ch\u1ecdn <b>s\u1ed1 ch\u01b0\u01a1ng</b> mu\u1ed1n t\u1ea1o (tr\u00e1nh qu\u00e1 t\u1ea3i c\u1ea3 cu\u1ed1n).\n"
    "<b>3.</b> Nh\u1eadp <b>t\u00ean truy\u1ec7n</b> (ho\u1eb7c /skip \u0111\u1ec3 d\u00f9ng t\u00ean file).\n"
    "<b>4.</b> Ch\u1ecdn <b>t\u1ed1c \u0111\u1ed9 \u0111\u1ecdc</b> v\u00e0 <b>\u0111\u1ecbnh d\u1ea1ng</b> audio.\n"
    "<b>5.</b> Ch\u1edd m\u00ecnh t\u1ea1o xong v\u00e0 g\u1eedi link t\u1ea3i v\u1ec1. \u2728\n\n"
    "\U0001f4c1 <i>H\u1ed7 tr\u1ee3: .txt, .epub, .pdf, .docx, .zip, .mobi\u2026 (t\u1ed1i \u0111a 20MB)</i>\n\n"
    "<b>L\u1ec7nh:</b>\n"
    "\u2022 /tts \u2014 B\u1eaft \u0111\u1ea7u t\u1ea1o audiobook\n"
    "\u2022 /skip \u2014 B\u1ecf qua \u0111\u1eb7t t\u00ean\n"
    "\u2022 /help \u2014 Xem h\u01b0\u1edbng d\u1eabn"
)


def handle_message(msg, state):
    chat_id = msg["chat"]["id"]
    user_id = (msg.get("from") or {}).get("id", 0)
    sessions = state["sessions"]
    skey = str(chat_id)

    if not allowed(user_id):
        send(chat_id, "\U0001f6ab B\u1ea1n kh\u00f4ng c\u00f3 quy\u1ec1n s\u1eed d\u1ee5ng bot n\u00e0y.")
        return

    # --- Document ---
    if "document" in msg:
        doc = msg["document"]
        name = os.path.basename((doc.get("file_name") or "input.txt").replace("\\", "/"))
        name = re.sub(r"[^\w.() -]", "_", name, flags=re.UNICODE)[:180] or "input.txt"
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXT:
            send(chat_id, "\u26a0\ufe0f \u0110\u1ecbnh d\u1ea1ng <code>%s</code> ch\u01b0a \u0111\u01b0\u1ee3c h\u1ed7 tr\u1ee3.\n\nH\u00e3y g\u1eedi c\u00e1c \u0111\u1ecbnh d\u1ea1ng: %s"
                 % (html.escape(ext), ", ".join(SUPPORTED_EXT)))
            return
        if doc.get("file_size", 0) > 20 * 1024 * 1024:
            send(chat_id, "\u26a0\ufe0f File l\u1edbn h\u01a1n <b>20MB</b> n\u00ean bot Telegram kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c.\n"
                 "B\u1ea1n h\u00e3y chia nh\u1ecf file, ho\u1eb7c d\u00f9ng b\u1ea3n ch\u1ea1y tr\u00ean m\u00e1y/VPS.")
            return
        dest = os.path.join(UPLOAD_DIR, skey, name)
        try:
            download_tg_file(doc["file_id"], dest)
        except Exception as e:  # noqa
            send(chat_id, "\u274c L\u1ed7i khi t\u1ea3i file: %s" % html.escape(str(e)))
            return
        sessions[skey] = {
            "step": "await_title",
            "filename": name,
            "input_path": os.path.relpath(dest, REPO_ROOT),
            "title": os.path.splitext(name)[0],
            "length_scale": "1.0",
            "format": "mp3",
            "install_calibre": "true" if ext in CALIBRE_EXT else "false",
            "start": "1",
            "limit": "0",
            "batch_size": "0",
        }
        send(chat_id,
             "\u2705 <b>\u0110\u00e3 nh\u1eadn file:</b> <code>%s</code>\n\n"
             "\U0001f50e \u0110ang ki\u1ec3m tra s\u1ed1 ch\u01b0\u01a1ng\u2026"
             % html.escape(name))
        # Xem truoc so chuong de hoi nguoi dung muon tao bao nhieu (tranh qua tai).
        info = probe_chapters(dest)
        total = int(info.get("count", 0)) if info else 0
        if total > 1:
            sessions[skey]["chapters_total"] = total
            ask_chapters(chat_id, sessions[skey])
        else:
            ask_title(chat_id, sessions[skey])
        return

    # --- Text / commands ---
    text = (msg.get("text") or "").strip()
    cmd = text.split("@")[0].lower()
    if cmd in ("/start",):
        send(chat_id, START_TEXT)
        return
    if cmd in ("/help",):
        send(chat_id, HELP_TEXT)
        return
    if cmd in ("/tts",):
        sessions[skey] = {"step": "await_file"}
        send(chat_id,
             "\U0001f4ce H\u00e3y g\u1eedi (\u0111\u00ednh k\u00e8m) <b>file ebook</b> b\u1ea1n mu\u1ed1n chuy\u1ec3n th\u00e0nh audio.\n\n"
             "<i>H\u1ed7 tr\u1ee3: .txt, .epub, .pdf, .docx, .zip, .mobi\u2026 (t\u1ed1i \u0111a 20MB)</i>")
        return

    sess = sessions.get(skey)
    if cmd in ("/skip",):
        if sess and sess.get("step") == "await_title":
            ask_speed(chat_id, sess)
        return

    # Dang cho nguoi dung go SO CHUONG (neu khong bam nut).
    if sess and sess.get("step") == "await_chapters" and text:
        parsed = parse_chapter_choice(text, sess.get("chapters_total", 0))
        if not parsed:
            send(chat_id,
                 "\u26a0\ufe0f Ch\u01b0a hi\u1ec3u. H\u00e3y nh\u1eadp m\u1ed9t <b>s\u1ed1</b> (vd <code>20</code>) "
                 "ho\u1eb7c m\u1ed9t <b>kho\u1ea3ng</b> (vd <code>1-30</code>), ho\u1eb7c b\u1ea5m n\u00fat b\u00ean tr\u00ean.")
            return
        start, limit = parsed
        sess["start"], sess["limit"] = str(start), str(limit)
        sess["batch_size"] = str(BATCH_SIZE_ALL) if limit == 0 else "0"
        ask_title(chat_id, sess)
        return

    if sess and sess.get("step") == "await_title" and text:
        sess["title"] = text
        ask_speed(chat_id, sess)
        return


def ask_chapters(chat_id, sess):
    sess["step"] = "await_chapters"
    total = int(sess.get("chapters_total", 0))
    send(chat_id,
         "\U0001f4da S\u00e1ch n\u00e0y c\u00f3 <b>%d ch\u01b0\u01a1ng</b>.\n\n"
         "G\u1eedi c\u1ea3 cu\u1ed1n m\u1ed9t l\u00fac c\u00f3 th\u1ec3 g\u00e2y <b>qu\u00e1 t\u1ea3i</b>. "
         "B\u1ea1n mu\u1ed1n t\u1ea1o bao nhi\u00eau ch\u01b0\u01a1ng?\n\n"
         "\U0001f449 Ch\u1ecdn nhanh b\u00ean d\u01b0\u1edbi, ho\u1eb7c nh\u1eadp <b>s\u1ed1</b> (vd <code>20</code>) "
         "ho\u1eb7c <b>kho\u1ea3ng ch\u01b0\u01a1ng</b> (vd <code>1-30</code>)." % total,
         reply_markup=chapter_keyboard(total))


def ask_title(chat_id, sess):
    sess["step"] = "await_title"
    send(chat_id,
         "\U0001f4dd <b>T\u00ean truy\u1ec7n</b> l\u00e0 g\u00ec? Nh\u1eadp t\u00ean, ho\u1eb7c g\u00f5 /skip \u0111\u1ec3 d\u00f9ng: <i>%s</i>"
         % html.escape(sess.get("title", "")))


def ask_speed(chat_id, sess):
    sess["step"] = "await_speed"
    send(chat_id,
         "\U0001f3ac <b>Truy\u1ec7n:</b> %s\n\n\u23f1\ufe0f Ch\u1ecdn <b>t\u1ed1c \u0111\u1ed9 \u0111\u1ecdc</b>:"
         % html.escape(sess["title"]),
         reply_markup=kb(SPEED_OPTIONS))


def handle_callback(cb, state):
    answer_cb(cb["id"])
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    data = cb.get("data", "")
    sess = state["sessions"].get(str(chat_id))
    if not sess:
        edit(chat_id, message_id,
             "\u231b Phi\u00ean \u0111\u00e3 h\u1ebft h\u1ea1n. H\u00e3y g\u1eedi l\u1ea1i file ho\u1eb7c g\u00f5 /tts \u0111\u1ec3 b\u1eaft \u0111\u1ea7u l\u1ea1i.")
        return

    if data.startswith("chap_"):
        choice = data[len("chap_"):]
        total = int(sess.get("chapters_total", 0))
        if choice == "all":
            sess["start"], sess["limit"] = "1", "0"
            sess["batch_size"] = str(BATCH_SIZE_ALL)
            label = "T\u1ea5t c\u1ea3 (%d ch\u01b0\u01a1ng)" % total
        else:
            sess["start"], sess["limit"] = "1", choice
            sess["batch_size"] = "0"
            label = "%s ch\u01b0\u01a1ng \u0111\u1ea7u" % choice
        edit(chat_id, message_id,
             "\U0001f4da S\u1ed1 ch\u01b0\u01a1ng: <b>%s</b>" % html.escape(label))
        ask_title(chat_id, sess)
        return

    if data in SPEED_OPTIONS:
        sess["length_scale"] = SPEED_OPTIONS[data][1]
        sess["step"] = "await_format"
        edit(chat_id, message_id,
             "\u23f1\ufe0f T\u1ed1c \u0111\u1ed9: <b>%s</b>\n\n\U0001f3b5 Gi\u1edd ch\u1ecdn <b>\u0111\u1ecbnh d\u1ea1ng</b> audio:"
             % SPEED_OPTIONS[data][0],
             reply_markup=kb(FORMAT_OPTIONS))
        return

    if data in FORMAT_OPTIONS:
        sess["format"] = FORMAT_OPTIONS[data][1]
        sess["step"] = "ready"
        sess["chat_id"] = chat_id
        edit(chat_id, message_id,
             "\U0001f3ac <b>Truy\u1ec7n:</b> %s\n"
             "\u23f1\ufe0f T\u1ed1c \u0111\u1ed9: <b>%s</b>  |  \U0001f3b5 \u0110\u1ecbnh d\u1ea1ng: <b>%s</b>\n\n"
             "\u23f3 <b>\u0110ang b\u1eaft \u0111\u1ea7u t\u1ea1o audio\u2026</b> M\u00ecnh s\u1ebd b\u00e1o khi xong nh\u00e9!"
             % (html.escape(sess["title"]), sess["length_scale"], FORMAT_OPTIONS[data][1]))
        return


# ------------------------------------------------------------ job runner

def git_commit_and_push(paths, message):
    """Commit selected paths and push with bounded conflict retries."""
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=REPO_ROOT, check=False)
    subprocess.run(["git", "config", "user.email",
                    "41898282+github-actions[bot]@users.noreply.github.com"],
                   cwd=REPO_ROOT, check=False)
    subprocess.run(["git", "add", "--", *paths], cwd=REPO_ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if staged.returncode == 0:
        return True
    subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, check=True)
    for attempt in range(1, 5):
        pull = subprocess.run(
            ["git", "pull", "--rebase", "--autostash", "origin", GH_BRANCH],
            cwd=REPO_ROOT,
        )
        push = subprocess.run(["git", "push", "origin", "HEAD:%s" % GH_BRANCH],
                              cwd=REPO_ROOT) if pull.returncode == 0 else pull
        if pull.returncode == 0 and push.returncode == 0:
            return True
        time.sleep(attempt * 3)
    return False


def dispatch_continuous_job(job_id):
    url = "%s/repos/%s/actions/workflows/%s/dispatches" % (
        GH_API, GH_REPO, WORKFLOW_FILE)
    response = requests.post(
        url, headers=GH_HEADERS,
        json={"ref": GH_BRANCH, "inputs": {"job_id": job_id, "retry_count": "0"}},
        timeout=30,
    )
    response.raise_for_status()


def get_published_release(tag):
    response = requests.get(
        "%s/repos/%s/releases/tags/%s" % (GH_API, GH_REPO, tag),
        headers=GH_HEADERS, timeout=30,
    )
    if response.status_code == 200:
        release = response.json()
        return release if not release.get("draft", False) else None
    return None


def process_ready_job(skey, sess):
    """Persist the ebook once and start a self-chaining audiobook workflow."""
    chat_id = sess.get("chat_id") or int(skey)
    job_id = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    input_abs = os.path.join(REPO_ROOT, sess["input_path"])
    job_dir = os.path.join(REPO_ROOT, "jobs", job_id)
    os.makedirs(job_dir, exist_ok=True)
    ebook_path = os.path.join(job_dir, os.path.basename(sess["filename"]))
    options = {
        "title": sess["title"],
        "format": sess["format"],
        "length_scale": sess["length_scale"],
        "start": sess.get("start", "1"),
        "limit": sess.get("limit", "0"),
        "continuous_batch_size": "10",
    }
    try:
        shutil.copy2(input_abs, ebook_path)
        with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
            json.dump(options, f, ensure_ascii=False, indent=2)
        rel_job = os.path.relpath(job_dir, REPO_ROOT)
        if not git_commit_and_push([rel_job], "audiobook %s: queue job" % job_id):
            raise RuntimeError("khong the day job len repository")
        dispatch_continuous_job(job_id)
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        send(chat_id, "\u274c Kh\u00f4ng th\u1ec3 kh\u1edfi \u0111\u1ed9ng job li\u00ean t\u1ee5c: %s"
             % html.escape(str(e)))
        return False

    try:
        os.remove(input_abs)
    except OSError:
        pass
    sess.pop("input_path", None)
    sess["step"] = "waiting_release"
    sess["job_id"] = job_id
    sess["release_tag"] = "audiobook-%s" % job_id
    sess["started_at"] = dt.datetime.utcnow().isoformat() + "Z"
    send(chat_id,
         "\u2705 Job <code>%s</code> \u0111\u00e3 b\u1eaft \u0111\u1ea7u. Bot s\u1ebd t\u1ef1 chia batch, "
         "t\u1ef1 ch\u1ea1y ti\u1ebfp v\u00e0 b\u00e1o khi to\u00e0n b\u1ed9 ho\u00e0n t\u1ea5t."
         % html.escape(job_id))
    return True


def check_waiting_job(skey, sess):
    release = get_published_release(sess.get("release_tag", ""))
    if not release:
        return False
    chat_id = sess.get("chat_id") or int(skey)
    send(chat_id,
         "\U0001f389 <b>Truy\u1ec7n: %s \u0111\u00e3 ho\u00e0n th\u00e0nh!</b>\n\n"
         "\U0001f4e6 S\u1ed1 batch: <b>%d</b>\n"
         "\U0001f517 <b>Link t\u1ea3i:</b>\n%s"
         % (html.escape(sess.get("title", "Audiobook")),
            len(release.get("assets", [])), release.get("html_url", "")))
    return True


# ------------------------------------------------------------ main

def poll_once(state, long_poll=False):
    """Poll 1 dot: doc update moi, dan dat hoi thoai, chay job da san sang."""
    timeout = 50 if long_poll else 0
    resp = tg("getUpdates", offset=state.get("offset", 0), timeout=timeout,
              allowed_updates=["message", "callback_query"])
    changed = False
    for upd in resp.get("result", []):
        state["offset"] = upd["update_id"] + 1
        changed = True
        try:
            if "message" in upd:
                handle_message(upd["message"], state)
            elif "callback_query" in upd:
                handle_callback(upd["callback_query"], state)
        except Exception as e:  # noqa - khong de 1 update lam sap ca vong lap
            print("Loi xu ly update: %s" % e, file=sys.stderr)

    # Xu ly cac job da du thong tin.
    for skey in list(state["sessions"].keys()):
        sess = state["sessions"][skey]
        if sess.get("step") == "ready":
            if process_ready_job(skey, sess):
                changed = True
        elif sess.get("step") == "waiting_release":
            if check_waiting_job(skey, sess):
                state["sessions"].pop(skey, None)
                changed = True
    return changed


def git_persist(message):
    """Persist conversation metadata only; never commit uploaded books."""
    try:
        if not git_commit_and_push(["bot/state/state.json"], message):
            print("Khong the day state bot sau 4 lan thu", file=sys.stderr)
    except Exception as e:  # noqa
        print("Loi luu state: %s" % e, file=sys.stderr)


def main():
    loop = "--loop" in sys.argv
    try:
        set_commands()
    except Exception:  # noqa
        pass
    state = load_state()
    # Uploads are intentionally not committed. Drop stale sessions after a
    # runner restart instead of retaining references to missing/private files.
    for skey in list(state.get("sessions", {})):
        rel = state["sessions"][skey].get("input_path")
        if rel and not os.path.isfile(os.path.join(REPO_ROOT, rel)):
            state["sessions"].pop(skey, None)

    if not loop:
        # Che do 1 luot (dung cho cron ngat quang).
        poll_once(state, long_poll=False)
        save_state(state)
        print("Xong 1 luot poll. offset=%s" % state.get("offset"))
        return

    # Che do CHAY LIEN TUC: long-poll cho den khi het ngan sach thoi gian, roi
    # thoat de lan chay ke tiep (cron + concurrency dam bao) tiep quan lien mach.
    budget = int(os.environ.get("MAX_RUNTIME_SEC", "20400"))  # ~5h40m
    started = time.time()
    print("Bat dau che do chay lien tuc (budget=%ss)." % budget)
    while time.time() - started < budget:
        try:
            changed = poll_once(state, long_poll=True)
        except Exception as e:  # noqa
            print("Loi poll: %s" % e, file=sys.stderr)
            time.sleep(3)
            continue
        if changed:
            save_state(state)
            git_persist("bot: cap nhat trang thai poll")
    save_state(state)
    git_persist("bot: luu state truoc khi ket thuc luot chay")
    print("Ket thuc luot chay lien tuc. offset=%s" % state.get("offset"))


if __name__ == "__main__":
    main()
