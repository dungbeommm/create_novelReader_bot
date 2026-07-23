"""Persistent planning/checkpoint helpers for chained GitHub Actions jobs."""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ia_upload import make_identifier, item_details_url  # noqa: E402


def atomic_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def write_env(values):
    path = os.environ.get("GITHUB_ENV")
    if not path:
        for key, value in values.items():
            print("%s=%s" % (key, value))
        return
    with open(path, "a", encoding="utf-8") as f:
        for key, value in values.items():
            value = str(value).replace("\n", " ").replace("\r", " ")
            f.write("%s=%s\n" % (key, value))


def probe(ebook, parser):
    run = subprocess.run(
        [sys.executable, parser, "--input", ebook, "--probe"],
        capture_output=True, text=True, check=True,
    )
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Parser probe returned no data")
    return json.loads(lines[-1])


def plan(args):
    job_dir = os.path.abspath(args.job_dir)
    options_path = os.path.join(job_dir, "job.json")
    progress_path = os.path.join(job_dir, "progress.json")
    with open(options_path, "r", encoding="utf-8") as f:
        options = json.load(f)

    if os.path.isfile(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            progress = json.load(f)
    else:
        info = probe(args.ebook, args.parser)
        total = as_int(info.get("count"), 0)
        requested_start = max(1, as_int(options.get("start"), 1))
        requested_limit = max(0, as_int(options.get("limit"), 0))
        final_chapter = total if requested_limit == 0 else min(
            total, requested_start + requested_limit - 1
        )
        if total < 1 or requested_start > final_chapter:
            raise RuntimeError("Invalid chapter range")
        configured_batch = as_int(options.get("continuous_batch_size"), 0)
        if configured_batch <= 0:
            configured_batch = as_int(os.environ.get("CONTINUOUS_BATCH_SIZE"), 20)
        configured_batch = min(50, max(1, configured_batch))
        job_id = os.path.basename(job_dir.rstrip("/"))
        title = options.get("title") or "audiobook"
        identifier = options.get("ia_identifier") or make_identifier(title, job_id)
        progress = {
            "version": 1,
            "title": title,
            "format": options.get("format") or "mp3",
            "length_scale": str(options.get("length_scale") or "1.0"),
            "requested_start": requested_start,
            "final_chapter": final_chapter,
            "total_book_chapters": total,
            "next_chapter": requested_start,
            "batch_size": configured_batch,
            "completed_batches": [],
            "status": "processing",
            "ia_identifier": identifier,
            "ia_item_url": item_details_url(identifier),
            "language": options.get("language") or "vie",
            "creator": options.get("creator") or "Piper TTS (Ngoc Huyen)",
            "cleaning": info.get("cleaning", {}),
        }
        atomic_json(progress_path, progress)

    # Bao dam item luon co identifier (voi progress cu chua co truong nay).
    identifier = progress.get("ia_identifier")
    if not identifier:
        identifier = make_identifier(
            progress.get("title", "audiobook"),
            os.path.basename(job_dir.rstrip("/")),
        )
        progress["ia_identifier"] = identifier
        progress["ia_item_url"] = item_details_url(identifier)
        atomic_json(progress_path, progress)

    start = as_int(progress.get("next_chapter"), 1)
    final_chapter = as_int(progress.get("final_chapter"), 0)
    if progress.get("status") == "complete" or start > final_chapter:
        progress["status"] = "complete"
        atomic_json(progress_path, progress)
        write_env({
            "ALREADY_COMPLETE": "true",
            "IA_IDENTIFIER": identifier,
            "IA_ITEM_URL": progress.get("ia_item_url", item_details_url(identifier)),
            "BOOK_TITLE": progress.get("title", "audiobook"),
        })
        return
    count = min(as_int(progress.get("batch_size"), 20), final_chapter - start + 1)
    end = start + count - 1
    first_upload = "true" if not progress.get("completed_batches") else "false"
    write_env({
        "ALREADY_COMPLETE": "false",
        "BATCH_START": start,
        "BATCH_LIMIT": count,
        "BATCH_END": end,
        "FINAL_CHAPTER": final_chapter,
        "BOOK_TITLE": progress.get("title", "audiobook"),
        "AUDIO_FORMAT": progress.get("format", "mp3"),
        "LENGTH_SCALE": progress.get("length_scale", "1.0"),
        "IA_IDENTIFIER": identifier,
        "IA_ITEM_URL": progress.get("ia_item_url", item_details_url(identifier)),
        "IA_FIRST_UPLOAD": first_upload,
        "IA_LANGUAGE": progress.get("language", "vie"),
        "IA_CREATOR": progress.get("creator", "Piper TTS (Ngoc Huyen)"),
    })
    print("Planned chapters %d-%d of %d -> archive.org item %s"
          % (start, end, final_chapter, identifier))


def advance(args):
    path = os.path.join(os.path.abspath(args.job_dir), "progress.json")
    with open(path, "r", encoding="utf-8") as f:
        progress = json.load(f)
    start, end = as_int(args.start), as_int(args.end)
    batches = progress.setdefault("completed_batches", [])
    if not any(as_int(x.get("start")) == start and as_int(x.get("end")) == end for x in batches):
        batches.append({"start": start, "end": end, "asset": args.asset})
    progress["next_chapter"] = max(as_int(progress.get("next_chapter"), 1), end + 1)
    done = progress["next_chapter"] > as_int(progress.get("final_chapter"), 0)
    progress["status"] = "complete" if done else "processing"
    atomic_json(path, progress)
    write_env({"JOB_COMPLETE": "true" if done else "false",
               "NEXT_CHAPTER": progress["next_chapter"]})
    print("Checkpoint saved; next chapter %s" % progress["next_chapter"])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--job-dir", required=True)
    p.add_argument("--ebook", required=True)
    p.add_argument("--parser", required=True)
    p.set_defaults(func=plan)
    a = sub.add_parser("advance")
    a.add_argument("--job-dir", required=True)
    a.add_argument("--start", required=True)
    a.add_argument("--end", required=True)
    a.add_argument("--asset", required=True)
    a.set_defaults(func=advance)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
