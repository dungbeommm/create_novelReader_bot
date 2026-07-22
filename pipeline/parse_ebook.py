"""Parse ebook files thanh danh sach chuong (chapters).

Ho tro:
  - .txt                    : tach chuong theo regex tieu de chuong
  - .epub                   : tach theo spine (moi tai lieu = 1 chuong)
  - .zip chua nhieu .txt    : moi file txt = 1 chuong (sap theo ten)
  - .mobi/.azw3/.fb2/.html  : chuyen ve text bang calibre `ebook-convert`
  - .docx                   : doc bang python-docx (fallback pandoc)
  - .pdf                    : doc bang pdftotext / pdfminer

Output:
  <out_dir>/001_<slug>.txt, 002_..., ...
  <out_dir>/manifest.json  -> [{"index":1,"title":"...","file":"001_...txt","chars":123}]

Vi du:
    python parse_ebook.py --input truyen.epub --out-dir chapters
    python parse_ebook.py --input truyen.txt  --out-dir chapters --max-chars 8000
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

# ------------------------------------------------------------------ helpers

# Cac mau tieu de chuong pho bien (tieng Viet co dau + khong dau + English).
# Dung IGNORECASE nen chi can liet ke chu thuong; ho tro so Arab va so La Ma.
CHAPTER_PATTERNS = [
    r"^\s*(?:ch\u01b0\u01a1ng|chuong|h\u1ed3i|hoi|ph\u1ea7n|phan|quy\u1ec3n|quyen|t\u1eadp|tap)\s+[\dIVXLCDM]+",
    r"^\s*(?:chapter|part|section|episode)\s+[\dIVXLCDM]+",
    r"^\s*[\dIVXLCDM]{1,4}\s*[\.\u2013\-:\uff1a]\s*\S+",
]
CHAPTER_RE = re.compile("|".join("(?:%s)" % p for p in CHAPTER_PATTERNS), re.IGNORECASE)


def slugify(text, max_len=40):
    """Chuyen tieu de -> slug ascii an toan cho ten file."""
    text = text.strip() or "chuong"
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    ascii_str = re.sub(r"[^A-Za-z0-9]+", "_", ascii_str).strip("_").lower()
    if not ascii_str:
        ascii_str = "chuong"
    return ascii_str[:max_len]


def read_text_file(path):
    """Doc file text, tu do encoding (utf-8, utf-8-sig, cp1258, latin-1)."""
    for enc in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def split_text_into_chapters(text, max_chars=0):
    """Tach mot chuoi text dai thanh danh sach chuong [{title, text}].

    - Neu tim thay tieu de chuong -> tach theo do.
    - Neu khong -> coi ca file la 1 chuong (hoac chia theo max_chars).
    """
    lines = text.splitlines()
    marks = [i for i, ln in enumerate(lines) if CHAPTER_RE.match(ln.strip())]

    chapters = []
    if marks:
        # Phan mo dau truoc chuong dau tien (neu co noi dung dang ke).
        if marks[0] > 0:
            head = "\n".join(lines[: marks[0]]).strip()
            if len(head) > 200:
                chapters.append({"title": "Mo dau", "text": head})
        for idx, start in enumerate(marks):
            end = marks[idx + 1] if idx + 1 < len(marks) else len(lines)
            title = lines[start].strip()
            body = "\n".join(lines[start:end]).strip()
            if body:
                chapters.append({"title": title, "text": body})
    else:
        chapters.append({"title": "Toan bo", "text": text.strip()})

    # Chia nho chuong qua dai theo max_chars (0 = khong chia).
    if max_chars and max_chars > 0:
        chapters = _enforce_max_chars(chapters, max_chars)
    return [c for c in chapters if c["text"].strip()]


def _enforce_max_chars(chapters, max_chars):
    out = []
    for c in chapters:
        text = c["text"]
        if len(text) <= max_chars:
            out.append(c)
            continue
        # Chia theo doan van (\n\n), gom lai duoi max_chars.
        paras = re.split(r"\n\s*\n", text)
        buf, part = "", 1
        for p in paras:
            if buf and len(buf) + len(p) > max_chars:
                out.append({"title": "%s (%d)" % (c["title"], part), "text": buf.strip()})
                buf, part = "", part + 1
            buf += ("\n\n" if buf else "") + p
        if buf.strip():
            out.append({"title": "%s (%d)" % (c["title"], part), "text": buf.strip()})
    return out


# ------------------------------------------------------------------ parsers

def parse_txt(path, max_chars):
    return split_text_into_chapters(read_text_file(path), max_chars)


def parse_zip(path, max_chars):
    """Zip chua nhieu .txt -> moi file 1 chuong. Neu chua epub -> parse epub."""
    chapters = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        txt_files, epub_files = [], []
        for root, _dirs, files in os.walk(tmp):
            for name in files:
                fp = os.path.join(root, name)
                low = name.lower()
                if low.endswith(".txt"):
                    txt_files.append(fp)
                elif low.endswith(".epub"):
                    epub_files.append(fp)
        txt_files.sort(key=lambda p: os.path.basename(p).lower())
        epub_files.sort()
        for fp in txt_files:
            title = os.path.splitext(os.path.basename(fp))[0]
            text = read_text_file(fp).strip()
            if text:
                chapters.append({"title": title, "text": text})
        for fp in epub_files:
            chapters.extend(parse_epub(fp, max_chars))
    if max_chars and max_chars > 0:
        chapters = _enforce_max_chars(chapters, max_chars)
    return [c for c in chapters if c["text"].strip()]


def parse_epub(path, max_chars):
    """Parse epub theo spine, moi tai lieu HTML = 1 chuong."""
    try:
        from ebooklib import epub
        import ebooklib
        from bs4 import BeautifulSoup
    except ImportError:
        print("[warn] Thieu ebooklib/bs4 -> fallback calibre", file=sys.stderr)
        return parse_via_calibre(path, max_chars)

    book = epub.read_epub(path)
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        heading = soup.find(["h1", "h2", "h3", "title"])
        title = heading.get_text(strip=True) if heading else ""
        text = soup.get_text("\n", strip=True)
        if len(text.strip()) < 20:
            continue
        if not title:
            title = text.strip().splitlines()[0][:80]
        chapters.append({"title": title, "text": text.strip()})
    if max_chars and max_chars > 0:
        chapters = _enforce_max_chars(chapters, max_chars)
    return [c for c in chapters if c["text"].strip()]


def parse_docx(path, max_chars):
    try:
        import docx
    except ImportError:
        return parse_via_calibre(path, max_chars)
    doc = docx.Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    return split_text_into_chapters(text, max_chars)


def parse_pdf(path, max_chars):
    # Uu tien pdftotext (poppler) -> nhanh, sach.
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            out_txt = tf.name
        try:
            subprocess.run(["pdftotext", "-enc", "UTF-8", path, out_txt], check=True)
            text = read_text_file(out_txt)
        finally:
            if os.path.exists(out_txt):
                os.remove(out_txt)
        return split_text_into_chapters(text, max_chars)
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return split_text_into_chapters("\n".join(parts), max_chars)
    except ImportError:
        raise RuntimeError("Khong doc duoc PDF: thieu pdftotext va pdfplumber")


def parse_via_calibre(path, max_chars):
    """Fallback chung: dung calibre `ebook-convert` de doi ve .txt."""
    if not shutil.which("ebook-convert"):
        raise RuntimeError(
            "Dinh dang nay can calibre (ebook-convert). Hay cai calibre trong workflow."
        )
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        out_txt = tf.name
    try:
        subprocess.run(
            ["ebook-convert", path, out_txt, "--enable-heuristics"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        text = read_text_file(out_txt)
    finally:
        if os.path.exists(out_txt):
            os.remove(out_txt)
    return split_text_into_chapters(text, max_chars)


PARSERS = {
    ".txt": parse_txt,
    ".zip": parse_zip,
    ".epub": parse_epub,
    ".docx": parse_docx,
    ".pdf": parse_pdf,
}
CALIBRE_EXTS = {".mobi", ".azw3", ".azw", ".fb2", ".html", ".htm", ".rtf", ".lit", ".pdb"}


def parse_ebook(path, max_chars=0):
    ext = os.path.splitext(path)[1].lower()
    if ext in PARSERS:
        return PARSERS[ext](path, max_chars)
    if ext in CALIBRE_EXTS:
        return parse_via_calibre(path, max_chars)
    # Thu doc nhu text thuan neu khong ro dinh dang.
    print("[warn] Dinh dang la %r, thu doc nhu text" % ext, file=sys.stderr)
    return parse_txt(path, max_chars)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Parse ebook -> danh sach chuong")
    ap.add_argument("--input", required=True, help="File ebook dau vao")
    ap.add_argument("--out-dir", default="chapters", help="Thu muc output")
    ap.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="Chia nho chuong dai hon N ky tu (0 = khong chia)",
    )
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print("Loi: khong tim thay file %r" % args.input, file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)
    chapters = parse_ebook(args.input, args.max_chars)
    if not chapters:
        print("Loi: khong trich xuat duoc noi dung nao", file=sys.stderr)
        sys.exit(2)

    manifest = []
    for i, ch in enumerate(chapters, start=1):
        slug = slugify(ch["title"])
        fname = "%03d_%s.txt" % (i, slug)
        fpath = os.path.join(args.out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(ch["text"])
        manifest.append(
            {"index": i, "title": ch["title"][:200], "file": fname, "chars": len(ch["text"])}
        )
        print("  [%03d] %-45s %6d ky tu" % (i, ch["title"][:45], len(ch["text"])))

    with open(os.path.join(args.out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    total = sum(m["chars"] for m in manifest)
    print("\nHoan tat: %d chuong, tong %d ky tu -> %s" % (len(manifest), total, args.out_dir))


if __name__ == "__main__":
    main()
