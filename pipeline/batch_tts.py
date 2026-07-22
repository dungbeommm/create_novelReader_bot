"""Batch TTS theo chuong bang Piper (giong Ngoc Huyen) + convert + dong goi.

Doc:
  <chapters_dir>/manifest.json  (do parse_ebook.py tao)
  job.json                       (option nguoi dung, tuy chon)

Quy trinh:
  1. Load PiperVoice 1 lan.
  2. Voi moi chuong -> synthesize WAV.
  3. Convert sang dinh dang dich (mp3/wav/m4b) bang ffmpeg.
  4. Dong goi:
       - format == m4b: gop tat ca thanh 1 audiobook co chapter marks.
       - package == zip (va nhieu file): nen .zip.
       - package == single (1 chuong): giu file don.

Output: cac file cuoi cung nam trong <out_dir> (mac dinh: release/).

Vi du:
    python batch_tts.py --chapters-dir chapters --out-dir release \\
        --title "Ten Truyen" --format mp3 --length-scale 1.0 --package zip
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import wave

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(BASE_DIR, "..", "voice", "ngochuyennew.onnx")
DEFAULT_CONFIG = os.path.join(BASE_DIR, "..", "voice", "ngochuyennew.onnx.json")


# ------------------------------------------------------------ piper synth

def load_voice(model, config):
    from piper import PiperVoice
    print("Dang tai model Piper: %s" % model, flush=True)
    return PiperVoice.load(model, config_path=config)


def synth_to_wav(voice, text, out_wav, length_scale=None, noise_scale=None, noise_w=None):
    kwargs = {}
    if length_scale is not None:
        kwargs["length_scale"] = length_scale
    if noise_scale is not None:
        kwargs["noise_scale"] = noise_scale
    if noise_w is not None:
        kwargs["noise_w"] = noise_w
    with wave.open(out_wav, "wb") as wav_file:
        # Ho tro ca API moi (>=1.3) va cu (1.2.x).
        if hasattr(voice, "synthesize_wav") and not kwargs:
            voice.synthesize_wav(text, wav_file)
        else:
            try:
                voice.synthesize(text, wav_file, **kwargs)
            except TypeError:
                voice.synthesize_wav(text, wav_file)


# ------------------------------------------------------------ ffmpeg utils

def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Thieu ffmpeg. Hay cai ffmpeg trong moi truong chay.")


def wav_duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def convert_audio(in_wav, out_path, fmt):
    """Convert WAV -> mp3/ogg/opus/wav bang ffmpeg."""
    if fmt == "wav":
        shutil.copyfile(in_wav, out_path)
        return
    codec = {
        "mp3": ["-codec:a", "libmp3lame", "-qscale:a", "3"],
        "ogg": ["-codec:a", "libvorbis", "-qscale:a", "4"],
        "opus": ["-codec:a", "libopus", "-b:a", "48k"],
        "m4a": ["-codec:a", "aac", "-b:a", "128k"],
    }.get(fmt, ["-codec:a", "libmp3lame", "-qscale:a", "3"])
    subprocess.run(
        ["ffmpeg", "-y", "-i", in_wav, *codec, out_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def build_m4b(wav_files, titles, out_path, title):
    """Gop nhieu WAV thanh 1 file .m4b co chapter marks."""
    # 1. Tao FFMETADATA voi moc chuong.
    meta_lines = [";FFMETADATA1", "title=%s" % _clean(title)]
    start_ms = 0
    concat_list = []
    for wav, chap_title in zip(wav_files, titles):
        dur_ms = int(wav_duration(wav) * 1000)
        end_ms = start_ms + dur_ms
        meta_lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            "START=%d" % start_ms,
            "END=%d" % end_ms,
            "title=%s" % _clean(chap_title),
        ]
        start_ms = end_ms
        concat_list.append("file '%s'" % os.path.abspath(wav).replace("'", r"'\''"))

    workdir = os.path.dirname(os.path.abspath(out_path)) or "."
    meta_path = os.path.join(workdir, "_chapters.txt")
    list_path = os.path.join(workdir, "_concat.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(meta_lines))
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_list))

    # 2. Concat + mux metadata -> m4b (aac).
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-i", meta_path, "-map_metadata", "1",
            "-codec:a", "aac", "-b:a", "128k",
            out_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(meta_path)
    os.remove(list_path)


def _clean(s):
    return re.sub(r"[\r\n=;]", " ", str(s)).strip()


# ------------------------------------------------------------ job options

def load_job_options(job_path):
    """Doc job.json neu co. Tra ve dict option da chuan hoa."""
    opts = {}
    if job_path and os.path.isfile(job_path):
        with open(job_path, "r", encoding="utf-8") as f:
            opts = json.load(f)
    return opts


def pick(cli_val, opts, key, default):
    if cli_val is not None:
        return cli_val
    if key in opts and opts[key] not in (None, ""):
        return opts[key]
    return default


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Batch TTS theo chuong bang Piper")
    ap.add_argument("--chapters-dir", default="chapters")
    ap.add_argument("--out-dir", default="release")
    ap.add_argument("--work-dir", default="work_audio", help="Thu muc WAV tam")
    ap.add_argument("--job", default=None, help="File job.json chua option")
    ap.add_argument("--title", default=None, help="Ten truyen")
    ap.add_argument("--format", default=None, choices=["mp3", "wav", "m4b", "ogg", "opus", "m4a"])
    ap.add_argument("--package", default=None, choices=["auto", "zip", "single", "files"])
    ap.add_argument("--length-scale", type=float, default=None)
    ap.add_argument("--noise-scale", type=float, default=None)
    ap.add_argument("--noise-w", type=float, default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args()

    opts = load_job_options(args.job)
    title = pick(args.title, opts, "title", "audiobook")
    fmt = pick(args.format, opts, "format", "mp3")
    package = pick(args.package, opts, "package", "auto")
    length_scale = pick(args.length_scale, opts, "length_scale", None)
    if length_scale is not None:
        length_scale = float(length_scale)
    noise_scale = pick(args.noise_scale, opts, "noise_scale", None)
    noise_w = pick(args.noise_w, opts, "noise_w", None)

    manifest_path = os.path.join(args.chapters_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("Loi: khong tim thay %s" % manifest_path, file=sys.stderr)
        sys.exit(1)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if not manifest:
        print("Loi: manifest rong", file=sys.stderr)
        sys.exit(2)

    ensure_ffmpeg()
    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    voice = load_voice(args.model, args.config)

    title_slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower() or "audiobook"
    wav_files, out_files, titles = [], [], []

    for m in manifest:
        idx = m["index"]
        stem = os.path.splitext(m["file"])[0]
        txt_path = os.path.join(args.chapters_dir, m["file"])
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            continue
        wav_path = os.path.join(args.work_dir, stem + ".wav")
        print("[%03d/%03d] TTS: %s (%d ky tu)" % (idx, len(manifest), m["title"][:40], len(text)), flush=True)
        synth_to_wav(voice, text, wav_path, length_scale, noise_scale, noise_w)
        wav_files.append(wav_path)
        titles.append(m["title"])

        if fmt != "m4b":
            out_path = os.path.join(args.out_dir, stem + "." + fmt)
            convert_audio(wav_path, out_path, fmt)
            out_files.append(out_path)

    if not wav_files:
        print("Loi: khong tao duoc audio nao", file=sys.stderr)
        sys.exit(3)

    # ---- Dong goi ket qua ----
    final_artifacts = []
    if fmt == "m4b":
        out_path = os.path.join(args.out_dir, title_slug + ".m4b")
        print("Dang gop %d chuong thanh m4b..." % len(wav_files), flush=True)
        build_m4b(wav_files, titles, out_path, title)
        final_artifacts.append(out_path)
    else:
        multiple = len(out_files) > 1
        want_zip = package == "zip" or (package == "auto" and multiple)
        if want_zip:
            zip_base = os.path.join(args.out_dir, title_slug)
            print("Dang nen %d file thanh zip..." % len(out_files), flush=True)
            shutil.make_archive(zip_base, "zip", args.out_dir)
            # Xoa file le, chi giu zip.
            for fp in out_files:
                if os.path.exists(fp):
                    os.remove(fp)
            final_artifacts.append(zip_base + ".zip")
        else:
            final_artifacts.extend(out_files)

    # Ghi summary de workflow / bot doc lai.
    summary = {
        "title": title,
        "chapters": len(wav_files),
        "format": fmt,
        "package": package,
        "artifacts": [os.path.basename(p) for p in final_artifacts],
        "total_seconds": round(sum(wav_duration(w) for w in wav_files), 1),
    }
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\nHoan tat!")
    print("  Chuong : %d" % summary["chapters"])
    print("  Thoi luong: %.1f phut" % (summary["total_seconds"] / 60.0))
    print("  File   : %s" % ", ".join(summary["artifacts"]))


if __name__ == "__main__":
    main()
