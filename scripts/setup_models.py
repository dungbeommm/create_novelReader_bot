"""Setup models for GitHub Actions environment: Hachimi translation model and Piper TTS voice."""
import argparse
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("setup_models")

VOICE_DIR = ROOT / 'models' / 'voices'
VOICE_DIR.mkdir(parents=True, exist_ok=True)

def download_file(url, target_path, min_bytes=1024):
    if target_path.is_file() and target_path.stat().st_size >= min_bytes:
        log.info("File exists: %s (%d bytes)", target_path.name, target_path.stat().st_size)
        return True
    log.info("Downloading %s -> %s ...", url, target_path.name)
    tmp_path = target_path.with_suffix('.tmp')
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, 'wb') as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
    if tmp_path.stat().st_size < min_bytes:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"Downloaded file too small: {tmp_path.stat().st_size} bytes")
    tmp_path.replace(target_path)
    log.info("Saved %s (%d bytes)", target_path.name, target_path.stat().st_size)
    return True

def setup_voice(voice_id="ngochuyennew"):
    base_url = f"https://raw.githubusercontent.com/dungbeommm/NovelReader_voices/main/voices/low/low-{voice_id}"
    onnx_file = VOICE_DIR / f"{voice_id}.onnx"
    json_file = VOICE_DIR / f"{voice_id}.onnx.json"
    download_file(f"{base_url}/{voice_id}.onnx.json", json_file, min_bytes=100)
    download_file(f"{base_url}/{voice_id}.onnx", onnx_file, min_bytes=10 * 1024 * 1024)

def setup_translation(model_key="HachimiMT-60-QT"):
    from translation.engines import LocalEngine
    log.info("Checking translation model: %s ...", model_key)
    engine = LocalEngine(model_key)
    engine.load()
    log.info("Translation model %s is ready!", model_key)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='HachimiMT-60-QT')
    parser.add_argument('--voice', default='ngochuyennew')
    args = parser.parse_args()

    setup_voice(args.voice)
    setup_translation(args.model)
    log.info("All setup complete!")

if __name__ == '__main__':
    main()
