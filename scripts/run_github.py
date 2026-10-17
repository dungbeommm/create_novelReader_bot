"""Run a finite Actions bot session; Docker on your own host is the 24/7 option."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integrations.checkpoint import restore, save


def stop(proc, timeout=90):
    if proc is not None and proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes', type=int, default=45)
    parser.add_argument('--checkpoint-minutes', type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.minutes <= 300 or not 5 <= args.checkpoint_minutes <= 60:
        parser.error('minutes: 1–300; checkpoint-minutes: 5–60')
    if not os.getenv('ALLOWED_USER_IDS') or not os.getenv('TELEGRAM_BOT_TOKEN'):
        parser.error('Thiếu TELEGRAM_BOT_TOKEN/ALLOWED_USER_IDS.')
    if os.getenv('CLOUD_UPLOAD', 'auto').lower() == 'off':
        parser.error('Actions cần bật lưu cloud; không đặt CLOUD_UPLOAD=off.')
    data = Path(os.environ.get('BOT_DATA', str(ROOT/'data/telegram'))).resolve()
    os.environ['BOT_DATA'] = str(data)
    os.environ['TTS_URL'] = 'http://127.0.0.1:8010'
    restore(data)
    data.mkdir(parents=True, exist_ok=True)
    # Validate write permissions/checkpoint setup before accepting any user jobs.
    save(data)
    tts = bot = None
    running = True
    def request_stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        tts = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'tts.server:app',
            '--host', '127.0.0.1', '--port', '8010', '--workers', '1', '--no-access-log'], cwd=ROOT)
        for _ in range(90):
            if not running:
                return
            if tts.poll() is not None:
                raise RuntimeError('TTS dừng khi khởi động.')
            try:
                import json
                with urllib.request.urlopen(os.environ['TTS_URL']+'/health', timeout=2) as response:
                    health = json.load(response)
                if not health.get('voice_present'):
                    raise RuntimeError('Thiếu models/voices/ngochuyennew.onnx.')
                break
            except (OSError, TimeoutError):
                time.sleep(2)
        else:
            raise RuntimeError('TTS chưa sẵn sàng sau 180 giây.')
        bot = subprocess.Popen([sys.executable, str(ROOT/'telegram/bot.py')], cwd=ROOT)
        deadline = time.monotonic() + args.minutes * 60
        checkpoint_at = time.monotonic() + args.checkpoint_minutes * 60
        while running and time.monotonic() < deadline:
            if bot.poll() is not None or tts.poll() is not None:
                raise RuntimeError('Bot/TTS đã dừng bất thường; xem log Actions.')
            if time.monotonic() >= checkpoint_at:
                save(data)
                checkpoint_at = time.monotonic() + args.checkpoint_minutes * 60
            time.sleep(2)
    finally:
        stop(bot, timeout=2100)
        stop(tts)
        # Fail the workflow if saving fails. Never silently discard the queue.
        save(data)


if __name__ == '__main__':
    main()
