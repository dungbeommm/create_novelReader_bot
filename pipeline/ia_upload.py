"""Dang tai (upload) file len Internet Archive (archive.org) qua IAS3 API.

Day la lop thay the cho "GitHub Release" cu: moi audiobook se tro thanh MOT
*item* tren archive.org, moi batch chuong duoc PUT vao item do. Link chia se
co dinh cua nguoi dung se la:  https://archive.org/details/<identifier>

Thong tin dang nhap (lay tai https://archive.org/account/s3.php) doc tu bien
moi truong:
  IA_ACCESS_KEY   S3 access key
  IA_SECRET_KEY   S3 secret key

CLI:
  # Tao item (lan dau) va upload 1 file:
  python pipeline/ia_upload.py upload --identifier my-item --file batch.zip \
      --title "Ten Truyen" --make-bucket --language vie

  # Upload them file vao item da co:
  python pipeline/ia_upload.py upload --identifier my-item --file batch2.zip

  # Danh dau item da hoan tat (ghi _COMPLETE.json de bot phat hien):
  python pipeline/ia_upload.py finalize --identifier my-item \
      --progress jobs/<job_id>/progress.json

Dung nhu module:
  from ia_upload import make_identifier, item_details_url, is_item_complete

Module co chu dich CHI phu thuoc `requests` de nhe va chay duoc trong GitHub
Actions ma khong can cai them thu vien `internetarchive`.
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import time
import unicodedata
import urllib.parse

try:
    import requests
except ImportError:  # pragma: no cover - requests luon co trong moi truong chay
    requests = None

# S3 endpoint cua Internet Archive (IAS3).
IA_S3_ENDPOINT = os.environ.get("IA_S3_ENDPOINT", "https://s3.us.archive.org")
IA_METADATA_ENDPOINT = os.environ.get(
    "IA_METADATA_ENDPOINT", "https://archive.org/metadata"
)

# Collection mac dinh cho tai khoan thuong (item cong khai, khong can duyet).
DEFAULT_COLLECTION = os.environ.get("IA_DEFAULT_COLLECTION", "opensource_audio")
DEFAULT_MEDIATYPE = "audio"

# Ten file danh dau "da hoan tat" (bot poll file nay de bao xong).
COMPLETE_MARKER = "_COMPLETE.json"


# --------------------------------------------------------------- identifier

def make_identifier(title, job_id):
    """Sinh identifier archive.org tu (title, job_id) mot cach TAT DINH.

    Nho tat dinh nen ca bot va workflow deu tinh ra cung identifier ma khong
    can trao doi -> bot biet truoc link chia se ngay khi dispatch job.

    Rang buoc cua archive.org: 1 chi dinh danh dai 3-100 ky tu, chi gom
    [A-Za-z0-9._-], khong bat dau/ket thuc bang ky tu dac biet.
    """
    base = unicodedata.normalize("NFKD", str(title or ""))
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()
    base = base[:40].strip("-")
    if not base:
        base = "audiobook"
    job_id = re.sub(r"[^A-Za-z0-9._-]", "-", str(job_id or "")).strip("-._")
    ident = ("%s-%s" % (base, job_id)).strip("-._") if job_id else base
    ident = re.sub(r"-{2,}", "-", ident)
    ident = ident[:100].strip("-._")
    return ident or ("audiobook-%s" % (job_id or "item"))


def item_details_url(identifier):
    return "https://archive.org/details/%s" % identifier


def item_download_url(identifier, filename=""):
    if filename:
        return "https://archive.org/download/%s/%s" % (
            identifier, urllib.parse.quote(filename))
    return "https://archive.org/download/%s" % identifier


# --------------------------------------------------------------- credentials

def get_credentials(access=None, secret=None):
    access = access or os.environ.get("IA_ACCESS_KEY", "").strip()
    secret = secret or os.environ.get("IA_SECRET_KEY", "").strip()
    if not access or not secret:
        raise RuntimeError(
            "Thieu IA_ACCESS_KEY / IA_SECRET_KEY. Lay tai "
            "https://archive.org/account/s3.php roi dat vao bien moi truong "
            "(hoac GitHub Secrets)."
        )
    return access, secret


# --------------------------------------------------------------- metadata

def _encode_meta_value(value):
    """Ma hoa gia tri metadata. Gia tri khong-ASCII phai boc uri(...)."""
    value = str(value)
    if all(ord(c) < 128 for c in value) and "\n" not in value and "\r" not in value:
        return value
    return "uri(" + urllib.parse.quote(value, safe="") + ")"


def build_meta_headers(metadata):
    """Bien dict metadata -> cac header x-archive-meta*.

    - Gia tri scalar: x-archive-meta-<field>
    - Gia tri list  : x-archive-meta01-<field>, x-archive-meta02-<field>, ...
    """
    headers = {}
    for field, value in metadata.items():
        if value is None:
            continue
        safe_field = re.sub(r"[^A-Za-z0-9-]", "-", str(field)).strip("-")
        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value, start=1):
                if item is None or item == "":
                    continue
                headers["x-archive-meta%02d-%s" % (i, safe_field)] = \
                    _encode_meta_value(item)
        else:
            headers["x-archive-meta-%s" % safe_field] = _encode_meta_value(value)
    return headers


def default_metadata(title, creator=None, language=None, description=None,
                     collection=None, subjects=None, mediatype=None):
    meta = {
        "mediatype": mediatype or DEFAULT_MEDIATYPE,
        "collection": collection or DEFAULT_COLLECTION,
        "title": title or "Audiobook",
    }
    if creator:
        meta["creator"] = creator
    if language:
        meta["language"] = language
    if description:
        meta["description"] = description
    if subjects:
        meta["subject"] = subjects
    return meta


# --------------------------------------------------------------- upload core

def upload_file(identifier, local_path, remote_name=None, metadata=None,
                make_bucket=False, access=None, secret=None, retries=4,
                size_hint=None, keep_old_version=False):
    """PUT mot file len item archive.org qua IAS3.

    make_bucket=True: tao item (bucket) neu chua co + gan metadata (chi can o
    LAN UPLOAD DAU TIEN cua item).
    """
    if requests is None:
        raise RuntimeError("Thu vien 'requests' chua duoc cai.")
    access, secret = get_credentials(access, secret)
    remote_name = remote_name or os.path.basename(local_path)
    quoted = urllib.parse.quote(remote_name)
    url = "%s/%s/%s" % (IA_S3_ENDPOINT.rstrip("/"), identifier, quoted)

    base_headers = {"Authorization": "LOW %s:%s" % (access, secret)}
    ctype, _ = mimetypes.guess_type(remote_name)
    if ctype:
        base_headers["Content-Type"] = ctype
    if not keep_old_version:
        # Ghi de neu file trung ten (tranh nhan ban khi chay lai batch).
        base_headers["x-archive-keep-old-version"] = "0"
    if make_bucket:
        base_headers["x-amz-auto-make-bucket"] = "1"
        base_headers.update(build_meta_headers(metadata or {}))
        if size_hint:
            base_headers["x-archive-size-hint"] = str(int(size_hint))

    file_size = os.path.getsize(local_path)
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with open(local_path, "rb") as f:
                headers = dict(base_headers)
                headers["Content-Length"] = str(file_size)
                resp = requests.put(url, headers=headers, data=f, timeout=1800)
            if resp.status_code in (200, 201):
                print("[IA] OK  %s -> %s (%d bytes)"
                      % (remote_name, identifier, file_size), flush=True)
                return {
                    "identifier": identifier,
                    "name": remote_name,
                    "details_url": item_details_url(identifier),
                    "download_url": item_download_url(identifier, remote_name),
                }
            # 503 = SlowDown (bi gioi han) -> cho lau hon roi thu lai.
            last_error = "HTTP %d: %s" % (resp.status_code, resp.text[:300])
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if (retry_after or "").isdigit() else attempt * 15
            print("[IA] Loi (%s), thu lai sau %ds (%d/%d)"
                  % (last_error, wait, attempt, retries), file=sys.stderr, flush=True)
            time.sleep(wait)
        except requests.RequestException as e:  # pragma: no cover - mang
            last_error = str(e)
            print("[IA] Loi mang: %s, thu lai (%d/%d)"
                  % (last_error, attempt, retries), file=sys.stderr, flush=True)
            time.sleep(attempt * 10)
    raise RuntimeError("Upload that bai sau %d lan thu: %s" % (retries, last_error))


# --------------------------------------------------------------- completion

def item_metadata(identifier, timeout=30):
    """Doc metadata cong khai cua item (khong can dang nhap)."""
    if requests is None:
        return {}
    try:
        r = requests.get("%s/%s" % (IA_METADATA_ENDPOINT.rstrip("/"), identifier),
                         timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa - best effort
        pass
    return {}


def item_file_names(identifier):
    meta = item_metadata(identifier)
    files = meta.get("files", []) if isinstance(meta, dict) else []
    return [f.get("name", "") for f in files]


def is_item_complete(identifier):
    """True neu item da co file danh dau hoan tat (_COMPLETE.json)."""
    return COMPLETE_MARKER in item_file_names(identifier)


def find_batch_file(identifier, prefix):
    """Tra ve ten file dau tien tren item bat dau bang <prefix>, hoac "".

    Dung de dam bao idempotency: neu batch da duoc upload roi (do lan chay truoc
    da thanh cong nhung buoc luu checkpoint that bai va workflow chay lai), thi
    KHONG tong hop + upload lai, tranh lang phi va tranh ghi de nhieu lan.
    """
    if not prefix:
        return ""
    for name in item_file_names(identifier):
        if name and name.startswith(prefix):
            return name
    return ""


def item_exists(identifier):
    return bool(item_metadata(identifier).get("files"))


# --------------------------------------------------------------- CLI

def _load_json(path):
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def cmd_upload(args):
    metadata = None
    if args.make_bucket:
        subjects = [s.strip() for s in (args.subject or "").split(",") if s.strip()]
        metadata = default_metadata(
            title=args.title,
            creator=args.creator,
            language=args.language,
            description=args.description,
            collection=args.collection,
            subjects=subjects or None,
        )
    result = upload_file(
        identifier=args.identifier,
        local_path=args.file,
        remote_name=args.name,
        metadata=metadata,
        make_bucket=args.make_bucket,
    )
    print(json.dumps(result, ensure_ascii=False))


def cmd_finalize(args):
    """Ghi file _COMPLETE.json len item de danh dau da xong."""
    progress = _load_json(args.progress)
    summary = {
        "done": True,
        "title": progress.get("title") or args.title or "Audiobook",
        "format": progress.get("format"),
        "total_book_chapters": progress.get("total_book_chapters"),
        "requested_start": progress.get("requested_start"),
        "final_chapter": progress.get("final_chapter"),
        "completed_batches": progress.get("completed_batches", []),
        "item_url": item_details_url(args.identifier),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = os.path.join(os.path.dirname(os.path.abspath(args.progress or ".")) or ".",
                       COMPLETE_MARKER)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    upload_file(
        identifier=args.identifier,
        local_path=tmp,
        remote_name=COMPLETE_MARKER,
        make_bucket=False,
    )
    try:
        os.remove(tmp)
    except OSError:
        pass
    print(item_details_url(args.identifier))


def cmd_find_batch(args):
    print(find_batch_file(args.identifier, args.prefix))


def cmd_status(args):
    print(json.dumps({
        "identifier": args.identifier,
        "details_url": item_details_url(args.identifier),
        "exists": item_exists(args.identifier),
        "complete": is_item_complete(args.identifier),
        "files": item_file_names(args.identifier),
    }, ensure_ascii=False, indent=2))


def cmd_identifier(args):
    print(make_identifier(args.title, args.job_id))


def main():
    ap = argparse.ArgumentParser(description="Internet Archive (archive.org) uploader")
    sub = ap.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Upload 1 file len item")
    up.add_argument("--identifier", required=True)
    up.add_argument("--file", required=True)
    up.add_argument("--name", default=None, help="Ten file tren archive (mac dinh = ten goc)")
    up.add_argument("--make-bucket", action="store_true", help="Tao item + gan metadata (lan dau)")
    up.add_argument("--title", default=None)
    up.add_argument("--creator", default=None)
    up.add_argument("--language", default=None)
    up.add_argument("--description", default=None)
    up.add_argument("--subject", default=None, help="Danh sach chu de, ngan cach dau phay")
    up.add_argument("--collection", default=None)
    up.set_defaults(func=cmd_upload)

    fin = sub.add_parser("finalize", help="Danh dau item da hoan tat")
    fin.add_argument("--identifier", required=True)
    fin.add_argument("--progress", default=None, help="Duong dan progress.json")
    fin.add_argument("--title", default=None)
    fin.set_defaults(func=cmd_finalize)

    st = sub.add_parser("status", help="Xem trang thai item")
    st.add_argument("--identifier", required=True)
    st.set_defaults(func=cmd_status)

    fb = sub.add_parser("find-batch",
                        help="In ten file batch da co tren item (rong neu chua co)")
    fb.add_argument("--identifier", required=True)
    fb.add_argument("--prefix", required=True)
    fb.set_defaults(func=cmd_find_batch)

    idc = sub.add_parser("identifier", help="In identifier tat dinh tu title + job_id")
    idc.add_argument("--title", required=True)
    idc.add_argument("--job-id", dest="job_id", required=True)
    idc.set_defaults(func=cmd_identifier)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
