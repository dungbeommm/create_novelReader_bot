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
import json
import os
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


# ------------------------------------------------------------ telegram api

def tg(method, **params):
    r = requests.post("%s/%s" % (TG_API, method), json=params, timeout=60)
    try:
        return r.json()
    except ValueError:
        return {"ok": False}


def send(chat_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg("sendMessage", **params)


def edit(chat_id, message_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg("editMessageText", **params)


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
    )
    if r.status_code not in (200, 201):
        r = requests.get(base + "/releases/tags/" + tag, headers=GH_HEADERS)
    rel = r.json()
    upload_url = rel.get("upload_url", "").split("{")[0]
    for fp in files:
        with open(fp, "rb") as f:
            data = f.read()
        uh = dict(GH_HEADERS)
        uh["Content-Type"] = "application/octet-stream"
        requests.post(upload_url, headers=uh, params={"name": os.path.basename(fp)}, data=data)
    # Lay lai release de co danh sach assets day du.
    r2 = requests.get(base + "/releases/tags/" + tag, headers=GH_HEADERS)
    return r2.json() if r2.status_code == 200 else rel


# ------------------------------------------------------------ handlers

START_TEXT = (
    "Xin chao! Toi tao audiobook giong Ngoc Huyen tu file ebook cua ban.\n\n"
    "Go /tts de bat dau: toi se yeu cau tai file, hoi TEN TRUYEN, roi cho chon "
    "toc do doc va dinh dang audio.\n"
    "Luu y: bot chay tren GitHub theo lich nen co the tra loi cham vai phut."
)
HELP_TEXT = (
    "Cach dung:\n"
    "1. /tts -> gui file ebook (.txt, .epub, .zip, .mobi, .pdf, .docx... <=20MB).\n"
    "2. Go TEN TRUYEN (hoac /skip de dung mac dinh).\n"
    "3. Chon TOC DO va DINH DANG.\n"
    "4. Cho GitHub tao xong -> toi gui link Release."
)


def handle_message(msg, state):
    chat_id = msg["chat"]["id"]
    user_id = (msg.get("from") or {}).get("id", 0)
    sessions = state["sessions"]
    skey = str(chat_id)

    if not allowed(user_id):
        send(chat_id, "Ban khong co quyen dung bot nay.")
        return

    # --- Document ---
    if "document" in msg:
        doc = msg["document"]
        name = doc.get("file_name") or "input.txt"
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXT:
            send(chat_id, "Dinh dang %r chua ho tro. Hay gui: %s" % (ext, ", ".join(SUPPORTED_EXT)))
            return
        if doc.get("file_size", 0) > 20 * 1024 * 1024:
            send(chat_id, "File > 20MB, bot Telegram khong tai duoc. Hay chia nho hoac dung bot VPS.")
            return
        dest = os.path.join(UPLOAD_DIR, skey, name)
        try:
            download_tg_file(doc["file_id"], dest)
        except Exception as e:  # noqa
            send(chat_id, "Loi tai file: %s" % e)
            return
        sessions[skey] = {
            "step": "await_title",
            "filename": name,
            "input_path": os.path.relpath(dest, REPO_ROOT),
            "title": os.path.splitext(name)[0],
            "length_scale": "1.0",
            "format": "mp3",
            "install_calibre": "true" if ext in CALIBRE_EXT else "false",
        }
        send(chat_id, "Da nhan file. TEN TRUYEN la gi? Go ten, hoac /skip de dung: %s"
             % os.path.splitext(name)[0])
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
        send(chat_id, "Hay gui (dinh kem) file ebook can chuyen thanh audio (<=20MB).")
        return

    sess = sessions.get(skey)
    if cmd in ("/skip",):
        if sess and sess.get("step") == "await_title":
            ask_speed(chat_id, sess)
        return

    if sess and sess.get("step") == "await_title" and text:
        sess["title"] = text
        ask_speed(chat_id, sess)
        return


def ask_speed(chat_id, sess):
    sess["step"] = "await_speed"
    send(chat_id, "Truyen: %s\nChon TOC DO doc:" % sess["title"], reply_markup=kb(SPEED_OPTIONS))


def handle_callback(cb, state):
    answer_cb(cb["id"])
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    data = cb.get("data", "")
    sess = state["sessions"].get(str(chat_id))
    if not sess:
        edit(chat_id, message_id, "Phien da het han. Hay gui lai file hoac /tts.")
        return

    if data in SPEED_OPTIONS:
        sess["length_scale"] = SPEED_OPTIONS[data][1]
        sess["step"] = "await_format"
        edit(chat_id, message_id, "Toc do: %s. Gio chon DINH DANG audio:" % SPEED_OPTIONS[data][0],
             reply_markup=kb(FORMAT_OPTIONS))
        return

    if data in FORMAT_OPTIONS:
        sess["format"] = FORMAT_OPTIONS[data][1]
        sess["step"] = "ready"
        sess["chat_id"] = chat_id
        edit(chat_id, message_id,
             "Truyen: %s\nToc do: %s | Dinh dang: %s\n\nBat dau tao audio..."
             % (sess["title"], sess["length_scale"], FORMAT_OPTIONS[data][1]))
        return


# ------------------------------------------------------------ job runner

def ensure_calibre():
    if shutil.which("ebook-convert"):
        return
    subprocess.run(["sudo", "apt-get", "install", "-y", "calibre"], check=False)


def process_ready_job(skey, sess):
    chat_id = sess.get("chat_id") or int(skey)
    job_id = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    work = os.path.join(WORK_DIR, job_id)
    chapters = os.path.join(work, "chapters")
    release = os.path.join(work, "release")
    input_abs = os.path.join(REPO_ROOT, sess["input_path"])

    if sess.get("install_calibre") == "true":
        ensure_calibre()

    try:
        subprocess.run(
            [PY, os.path.join(REPO_ROOT, "pipeline", "parse_ebook.py"),
             "--input", input_abs, "--out-dir", chapters, "--max-chars", "0"],
            check=True, cwd=REPO_ROOT,
        )
        subprocess.run(
            [PY, os.path.join(REPO_ROOT, "pipeline", "batch_tts.py"),
             "--chapters-dir", chapters, "--out-dir", release,
             "--title", sess["title"], "--format", sess["format"],
             "--length-scale", str(sess["length_scale"]), "--package", "auto"],
            check=True, cwd=REPO_ROOT,
        )
    except subprocess.CalledProcessError as e:
        send(chat_id, "Tao audio that bai (%s). Xem log GitHub Actions." % e)
        shutil.rmtree(work, ignore_errors=True)
        return

    files = [
        os.path.join(release, f) for f in sorted(os.listdir(release))
        if not f.endswith(".json")
    ]
    summary_path = os.path.join(release, "summary.json")
    body = ""
    if os.path.isfile(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            body = f.read()

    rel = create_release_with_assets(
        "audiobook-%s" % job_id, "Audiobook %s" % sess["title"], body, files
    )
    lines = ["Truyen: %s da hoan thanh!" % sess["title"], "Link nhu sau:", rel.get("html_url", ""), ""]
    for a in rel.get("assets", []):
        size_mb = a.get("size", 0) / (1024 * 1024)
        lines.append("- %s (%.1f MB): %s" % (a["name"], size_mb, a["browser_download_url"]))
    send(chat_id, "\n".join(lines))

    # Don dep file tam + upload.
    shutil.rmtree(work, ignore_errors=True)
    if os.path.exists(input_abs):
        os.remove(input_abs)


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
            process_ready_job(skey, sess)
            state["sessions"].pop(skey, None)
            changed = True
    return changed


def git_persist(message):
    """Commit + push thu muc bot/state de lan chay ke tiep tiep quan lien mach."""
    try:
        subprocess.run(["git", "add", "bot/state"], cwd=REPO_ROOT, check=False)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
        if staged.returncode != 0:
            subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, check=False)
            subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=REPO_ROOT, check=False)
            subprocess.run(["git", "push"], cwd=REPO_ROOT, check=False)
    except Exception as e:  # noqa
        print("Loi luu state: %s" % e, file=sys.stderr)


def main():
    loop = "--loop" in sys.argv
    state = load_state()

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
