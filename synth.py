"""CLI chuyen van ban tieng Viet thanh file WAV bang Piper TTS.

Vi du:
    python synth.py --text "Xin chao" --out output.wav
    python synth.py --text-file input.txt --out output.wav --length-scale 1.1
"""
import argparse
import os
import sys
import wave

from piper import PiperVoice

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(BASE_DIR, "voice", "ngochuyennew.onnx")
DEFAULT_CONFIG = os.path.join(BASE_DIR, "voice", "ngochuyennew.onnx.json")


def parse_args():
    p = argparse.ArgumentParser(description="Piper TTS - giong Ngoc Huyen (tieng Viet)")
    p.add_argument("--text", help="Van ban can doc")
    p.add_argument("--text-file", help="Doc van ban tu file (uu tien hon --text neu ca hai co)")
    p.add_argument("--out", default="output.wav", help="Duong dan file WAV output")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--length-scale", type=float, default=None, help="Toc do (lon hon = cham hon)")
    p.add_argument("--noise-scale", type=float, default=None)
    p.add_argument("--noise-w", type=float, default=None)
    return p.parse_args()


def main():
    args = parse_args()

    text = None
    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    elif args.text:
        text = args.text.strip()

    if not text:
        print("Loi: can cung cap --text hoac --text-file", file=sys.stderr)
        sys.exit(1)

    print(f"Dang tai model: {args.model}", flush=True)
    voice = PiperVoice.load(args.model, config_path=args.config)

    kwargs = {}
    if args.length_scale is not None:
        kwargs["length_scale"] = args.length_scale
    if args.noise_scale is not None:
        kwargs["noise_scale"] = args.noise_scale
    if args.noise_w is not None:
        kwargs["noise_w"] = args.noise_w

    print(f"Dang tao giong noi ({len(text)} ky tu)...", flush=True)

    # Uu tien API 1.2 vi API nay nhan cac tham so inference.
    with wave.open(args.out, "wb") as wav_file:
        if hasattr(voice, "synthesize"):
            voice.synthesize(text, wav_file, **kwargs)
        elif kwargs:
            raise RuntimeError("Phien ban Piper nay khong ho tro tuy chinh inference")
        else:
            voice.synthesize_wav(text, wav_file)

    size = os.path.getsize(args.out)
    print(f"Hoan tat! Da ghi {args.out} ({size} bytes)", flush=True)


if __name__ == "__main__":
    main()
