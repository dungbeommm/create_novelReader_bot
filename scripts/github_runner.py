"""GitHub Actions continuous runner watchdog.

Monitors the Telegram bot process, tracks execution time, and automatically
triggers the next GitHub Actions workflow run before the 6-hour limit is reached,
achieving a continuous, 24/7 self-perpetuating loop on GitHub.
"""
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [GitHubRunner] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("github_runner")

# GitHub Actions limit: 360 minutes (6 hours).
# Default safe threshold: 320 minutes (5 hours 20 minutes = 19,200 seconds).
MAX_RUN_SECONDS = int(os.getenv("RUNNER_MAX_SECONDS", 19200))
HARD_MAX_SECONDS = int(os.getenv("RUNNER_HARD_MAX_SECONDS", 20400))  # 5h 40m
CHECK_INTERVAL_SECONDS = 15
HANDOVER_WAIT_SECONDS = 45

DATA_DIR = ROOT / "data" / "telegram"
QUEUE_DB = DATA_DIR / "queue.sqlite3"

def is_job_active() -> bool:
    """Kiểm tra xem có tác vụ nào đang xử lý trong database không."""
    if not QUEUE_DB.is_file():
        return False
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=5)
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM jobs WHERE status = 'running' LIMIT 1").fetchone()
        conn.close()
        return bool(row)
    except Exception as e:
        log.warning("Không đọc được queue.sqlite3: %s", e)
        return False

def trigger_next_workflow() -> bool:
    """Gửi yêu cầu workflow_dispatch lên GitHub API để khởi chạy bản tiếp theo."""
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    workflow = os.getenv("WORKFLOW_FILE", "telegram_bot.yml")
    ref = os.getenv("GITHUB_REF_NAME", "main")

    if not repo:
        log.warning("Không có GITHUB_REPOSITORY trong môi trường. Bỏ qua trigger API (đang chạy local?).")
        return False
    if not token:
        log.error("Thiếu GITHUB_TOKEN hoặc GH_PAT để kích hoạt workflow kế tiếp!")
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Continuous-Telegram-Runner"
    }
    payload = json.dumps({"ref": ref}).encode("utf-8")

    log.info("Đang kích hoạt workflow tiếp theo qua GitHub API: %s (ref: %s)...", url, ref)

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201, 204):
                    log.info(">>> KÍCH HOẠT WORKFLOW MỚI THÀNH CÔNG! (Status %d)", resp.status)
                    return True
                log.warning("Phản hồi GitHub API: %d", resp.status)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.error("Lỗi HTTP GitHub API (Lần %d/3): %d %s - %s", attempt, e.code, e.reason, body)
            if e.code == 403 and "Resource not accessible by integration" in body:
                log.error("LƯU Ý: GITHUB_TOKEN mặc định bị chặn kích hoạt workflow. Hãy thêm Secret GH_PAT với quyền 'actions:write' vào Settings -> Secrets.")
        except Exception as e:
            log.error("Lỗi kết nối GitHub API (Lần %d/3): %s", attempt, e)
        time.sleep(3)

    return False

def push_state_to_branch():
    """Lưu database queue và cấu hình vào nhánh bot-state trên GitHub (nếu có quyền git)."""
    if not QUEUE_DB.is_file():
        return
    try:
        token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
        repo = os.getenv("GITHUB_REPOSITORY")
        if not token or not repo:
            return

        log.info("Đang sao lưu trạng thái bot (queue.sqlite3) lên git...")
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=False)
        subprocess.run(["git", "add", "-f", "data/telegram/queue.sqlite3"], check=False)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"], check=False)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", "chore: persist bot state before handover [skip ci]"], check=False)
            remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
            subprocess.run(["git", "push", remote_url, f"HEAD:{os.getenv('GITHUB_REF_NAME', 'main')}"], check=False)
            log.info("Đã sao lưu trạng thái thành công.")
    except Exception as exc:
        log.warning("Không thể commit trạng thái: %s", exc)

def main():
    log.info("================================================================")
    log.info(" KHỞI ĐỘNG RUNNER GIÁM SÁT LIÊN TỤC TRÊN GITHUB ACTIONS")
    log.info(" Thời gian an toàn mỗi chu kỳ: %d phút (~%.1f giờ)", MAX_RUN_SECONDS // 60, MAX_RUN_SECONDS / 3600)
    log.info("================================================================")

    start_time = time.time()
    bot_cmd = [sys.executable, str(ROOT / "telegram" / "bot.py")]

    log.info("Khởi động tiến trình bot Telegram: %s", " ".join(bot_cmd))
    bot_proc = subprocess.Popen(bot_cmd)

    triggered_next = False

    try:
        while True:
            ret = bot_proc.poll()
            if ret is not None:
                log.error("Tiến trình bot Telegram đã dừng đột ngột với mã thoát: %d", ret)
                time.sleep(5)
                log.info("Đang tự động khởi động lại bot...")
                bot_proc = subprocess.Popen(bot_cmd)

            elapsed = time.time() - start_time
            remaining = MAX_RUN_SECONDS - elapsed

            if int(elapsed) % 1800 < CHECK_INTERVAL_SECONDS:
                log.info("Thời gian đã chạy: %d phút | Còn lại an toàn: %d phút", int(elapsed // 60), max(0, int(remaining // 60)))

            if elapsed >= MAX_RUN_SECONDS:
                active = is_job_active()
                if active and elapsed < HARD_MAX_SECONDS:
                    log.info("Đang có tác vụ dịch/audio chạy dở; cho thêm thời gian hoàn thành (tối đa %d phút)...", HARD_MAX_SECONDS // 60)
                    time.sleep(CHECK_INTERVAL_SECONDS)
                    continue

                log.info(">>> ĐẠT NGƯỠNG AN TOÀN (%.1f GIỜ). TIẾN HÀNH BÀN GIAO SANG RUNNER TIẾP THEO...", elapsed / 3600)

                if not triggered_next:
                    triggered_next = trigger_next_workflow()

                push_state_to_branch()

                log.info("Đang đợi %d giây để runner mới sẵn sàng nhận lệnh Telegram...", HANDOVER_WAIT_SECONDS)
                time.sleep(HANDOVER_WAIT_SECONDS)

                log.info("Đang dừng bot cũ để bàn giao trọn vẹn...")
                bot_proc.terminate()
                try:
                    bot_proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    bot_proc.kill()
                    bot_proc.wait()

                log.info(">>> BÀN GIAO HOÀN TẤT THÀNH CÔNG! KẾT THÚC RUNNER HIỆN TẠI.")
                sys.exit(0)

            time.sleep(CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log.info("Nhận tín hiệu dừng (Ctrl+C). Đang đóng bot...")
        bot_proc.terminate()
        bot_proc.wait()
    except Exception as exc:
        log.exception("Lỗi không lường trước trong runner: %s", exc)
        bot_proc.terminate()
        bot_proc.wait()
        sys.exit(1)

if __name__ == '__main__':
    main()
