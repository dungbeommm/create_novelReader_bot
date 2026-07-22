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
import posixpath
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import unquote

# ------------------------------------------------------------------ helpers

# Cac mau tieu de chuong pho bien (tieng Viet co dau + khong dau + English).
# Dung IGNORECASE nen chi can liet ke chu thuong; ho tro so Arab va so La Ma.
CHAPTER_PATTERNS = [
    r"^\s*(?:ch\u01b0\u01a1ng|chuong|h\u1ed3i|hoi|ph\u1ea7n|phan|quy\u1ec3n|quyen|t\u1eadp|tap)\s+[\dIVXLCDM]+",
    r"^\s*(?:chapter|part|section|episode)\s+[\dIVXLCDM]+",
    r"^\s*[\dIVXLCDM]{1,4}\s*[\.\u2013\-:\uff1a]\s*\S+",
]
CHAPTER_RE = re.compile("|".join("(?:%s)" % p for p in CHAPTER_PATTERNS), re.IGNORECASE)

# More permissive matcher used for ebook block-level parsing. Real-world books
# frequently put chapter titles in <p> elements and use values such as 93+1.
EBOOK_CHAPTER_RE = re.compile(
    r"^\s*((?:chương|chuong|hồi|hoi|phần|phan|quyển|quyen|tập|tap|"
    r"chapter|part|section|episode)\s+"
    r"\d+(?:\s*[+./-]\s*\d+)*"
    r"(?:(?:\s*[:.\-–—]\s*|\s+)[^\r\n]{0,300})?)",
    re.IGNORECASE,
)
ROMAN_CHAPTER_RE = re.compile(
    r"^\s*((?i:chương|chuong|hồi|hoi|phần|phan|quyển|quyen|tập|tap|"
    r"chapter|part|section|episode)\s+[IVXLCDM]+"
    r"(?:(?:\s*[:.\-–—]\s*|\s+)[^\r\n]{0,300})?)\s*$"
)

URL_RE = re.compile(
    r"(?i)(?:https?://|www\.)[^\s<>\]\[(){}]+|"
    r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|vn|io|me|info)(?:/[^\s<>]*)?"
)
STRONG_NOISE_RE = re.compile(
    r"(?i)(?:\bdtv[\s-]*ebook\b|\bdocument outline\b|"
    r"truyện\s+(?:được\s+)?dịch\s+bởi|(?:convert|converted|biên tập|đóng gói)\s+bởi|"
    r"\b(?:kb|liên hệ)\s+zalo\b|\bzalo\s*[:：]?\s*\d|"
    r"\bmua\s+(?:truyện|full|list)\b|\bfull\s+list\b|"
    r"\b\d+\s*(?:k|nghìn)\s*(?:1|một)\s*bộ\b|"
    r"\b(?:facebook|telegram)\s*[:：]\s*[@\w])"
)
TITLE_AD_CUT_RE = re.compile(
    r"(?i)\s*(?:--+|——+|–{2,})\s*(?=(?:mình\s+có|zalo|mua|bán|full|liên hệ|kb\s+zalo))"
)
LAST_CLEAN_REPORT = {}


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


def _norm_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clean_inline(text):
    """Remove watermarks without deleting surrounding story text."""
    text = URL_RE.sub(" ", text)
    text = re.sub(r"\[/?(?:i|b|u|font|color|size)[^\]]*\]", "", text, flags=re.I)
    return _norm_space(text)


def _chapter_title(text):
    """Return a clean chapter title, or None when the block is not a title."""
    raw = _norm_space(text)
    m = EBOOK_CHAPTER_RE.match(raw) or ROMAN_CHAPTER_RE.match(raw)
    if not m:
        return None
    title = m.group(1).strip()
    cut = TITLE_AD_CUT_RE.search(title)
    if cut:
        title = title[:cut.start()].rstrip(" -–—:")
    # Some polluted headings append the advertisement without a separator.
    ad = STRONG_NOISE_RE.search(title)
    if ad and ad.start() > 8:
        title = title[:ad.start()].rstrip(" -–—,;:")
    return _clean_inline(title)[:240]


def _chapter_number(title):
    m = re.match(
        r"(?i)^\s*(?:chương|chuong|hồi|hoi|phần|phan|quyển|quyen|tập|tap|"
        r"chapter|part|section|episode)\s+(\d+)",
        title or "",
    )
    return int(m.group(1)) if m else None


def _metadata_noise_values(book):
    values = set()
    for namespace, key in (("DC", "title"), ("DC", "creator"), ("DC", "publisher")):
        try:
            for value, _attrs in book.get_metadata(namespace, key):
                value = _norm_space(value).lower().strip(" -–—:|_")
                if 2 < len(value) < 160:
                    values.add(value)
        except Exception:
            pass
    return values


def _read_epub_documents(path):
    """Read metadata and spine documents using only the Python standard library.

    This keeps EPUB support available even when ebooklib is missing and avoids
    extracting the archive to disk. Paths are normalized and constrained to
    members inside the EPUB ZIP.
    """
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        opf_path = None
        try:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            node = container.find(".//{*}rootfile")
            if node is not None:
                opf_path = node.attrib.get("full-path")
        except (KeyError, ET.ParseError):
            pass
        if not opf_path:
            opfs = sorted(n for n in names if n.lower().endswith(".opf"))
            if not opfs:
                raise RuntimeError("EPUB khong co package OPF")
            opf_path = opfs[0]
        if opf_path not in names:
            raise RuntimeError("EPUB tham chieu OPF khong ton tai")

        opf = ET.fromstring(zf.read(opf_path))
        opf_dir = posixpath.dirname(opf_path)
        manifest = {}
        for item in opf.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib.get("id")
            href = unquote((item.attrib.get("href") or "").split("#", 1)[0])
            media = item.attrib.get("media-type", "")
            if item_id and href:
                member = posixpath.normpath(posixpath.join(opf_dir, href))
                if member.startswith("../") or member.startswith("/"):
                    continue
                manifest[item_id] = (member, media)

        metadata_noise = set()
        for tag in ("title", "creator", "publisher"):
            for node in opf.findall(".//{*}metadata/{*}%s" % tag):
                value = _norm_space(node.text).lower().strip(" -–—:|_")
                if 2 < len(value) < 160:
                    metadata_noise.add(value)

        ordered = []
        for ref in opf.findall(".//{*}spine/{*}itemref"):
            item = manifest.get(ref.attrib.get("idref"))
            if not item:
                continue
            member, media = item
            if media not in {"application/xhtml+xml", "text/html"}:
                continue
            if member in names:
                ordered.append((member, zf.read(member)))

        # Malformed EPUB fallback: use manifest order, never arbitrary ZIP order.
        if not ordered:
            for member, media in manifest.values():
                if media in {"application/xhtml+xml", "text/html"} and member in names:
                    ordered.append((member, zf.read(member)))
        return metadata_noise, ordered


def _is_noise_block(text, metadata_noise):
    cleaned = _clean_inline(text)
    if not cleaned:
        return True
    key = cleaned.lower().strip(" -–—:|_☆")
    if key in metadata_noise:
        return True
    if key in {"mục lục", "muc luc", "contents", "table of contents", "index",
               "document outline", "cover", "duyên phận 0"}:
        return True
    if STRONG_NOISE_RE.search(cleaned):
        return True
    # Separators add long, unnatural pauses to TTS and carry no story content.
    if re.fullmatch(r"[-–—_=*☆oO.\s]{3,}", cleaned):
        return True
    return False


def _html_blocks(soup):
    """Extract semantic blocks without duplicating text from wrapper divs."""
    block_names = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote"}
    blocks = []
    for el in soup.find_all(list(block_names)):
        # Nested block tags are represented by their children only.
        if any(parent.name in block_names for parent in el.parents):
            continue
        raw = el.get_text("\n", strip=True)
        if not _norm_space(raw):
            continue
        href_links = [a for a in el.find_all("a") if (a.get("href") or "").strip()]
        blocks.append({
            "raw": raw,
            "tag": el.name,
            "has_href": bool(href_links),
            "href_count": len(href_links),
        })
    if not blocks:
        raw = soup.get_text("\n", strip=True)
        if _norm_space(raw):
            blocks.append({"raw": raw, "tag": "body", "has_href": False, "href_count": 0})
    return blocks


def _validate_chapter_sequence(chapters):
    numbers = [_chapter_number(c["title"]) for c in chapters]
    numbers = [n for n in numbers if n is not None]
    missing, duplicates, backwards = [], [], []
    seen = Counter(numbers)
    duplicates = sorted(n for n, count in seen.items() if count > 1)
    for a, b in zip(numbers, numbers[1:]):
        if b < a:
            backwards.append({"from": a, "to": b})
        elif b > a + 1 and b - a <= 1000:
            missing.extend(range(a + 1, b))
    return {
        "numbered_chapters": len(numbers),
        "missing_numbers": sorted(set(missing))[:500],
        "duplicate_numbers": duplicates[:500],
        "backward_jumps": backwards[:100],
    }


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
        # A single paragraph can itself exceed the limit. Split it on sentence
        # boundaries, then hard-cut only sentences that are still too long.
        safe_paras = []
        for para in paras:
            if len(para) <= max_chars:
                safe_paras.append(para)
                continue
            sentences = re.split(r"(?<=[.!?…])\s+", para)
            for sentence in sentences:
                safe_paras.extend(
                    sentence[i:i + max_chars]
                    for i in range(0, len(sentence), max_chars)
                    if sentence[i:i + max_chars]
                )
        paras = safe_paras
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
            root = os.path.realpath(tmp)
            for member in zf.infolist():
                target = os.path.realpath(os.path.join(root, member.filename))
                if target != root and not target.startswith(root + os.sep):
                    raise RuntimeError("ZIP chua duong dan khong an toan: %s" % member.filename)
                if member.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
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
    """Parse dirty real-world EPUBs into true chapters.

    File boundaries are ignored: one HTML file may contain many chapters, and a
    chapter may continue in the next file. TOCs, URLs, repeated site branding,
    converter credits and embedded advertisements are removed at block level.
    """
    global LAST_CLEAN_REPORT
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("Can cai beautifulsoup4 de doc EPUB")

    metadata_noise, ordered_items = _read_epub_documents(path)
    chapters, current = [], None
    report = {
        "source_format": "epub",
        "documents_scanned": 0,
        "toc_links_removed": 0,
        "url_occurrences_removed": 0,
        "noise_blocks_removed": 0,
        "content_blocks_kept": 0,
    }
    # Follow the EPUB spine so chapters retain reading order and navigation or
    # unreferenced documents are not synthesized accidentally.
    fallback_documents = []
    for _member_name, item_content in ordered_items:
        report["documents_scanned"] += 1
        soup = BeautifulSoup(item_content, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()

        blocks = _html_blocks(soup)
        fallback_text = []
        for block in blocks:
            raw = block["raw"]
            title = _chapter_title(raw)

            # A chapter-looking linked block is a TOC entry, not story content.
            if title and block["has_href"]:
                report["toc_links_removed"] += 1
                continue

            url_count = len(URL_RE.findall(raw))
            if url_count:
                report["url_occurrences_removed"] += url_count

            if title:
                if current and current["parts"]:
                    chapters.append({
                        "title": current["title"],
                        "text": "\n\n".join(current["parts"]).strip(),
                    })
                current = {"title": title, "parts": []}
                continue

            if _is_noise_block(raw, metadata_noise):
                report["noise_blocks_removed"] += 1
                continue

            cleaned = _clean_inline(raw)
            if not cleaned:
                continue
            fallback_text.append(cleaned)
            if current is not None:
                current["parts"].append(cleaned)
                report["content_blocks_kept"] += 1

        if fallback_text:
            fallback_documents.append({
                "title": _norm_space(fallback_text[0])[:80] or "Noi dung",
                "text": "\n\n".join(fallback_text),
            })

    if current and current["parts"]:
        chapters.append({
            "title": current["title"],
            "text": "\n\n".join(current["parts"]).strip(),
        })

    # Books without recognizable chapter headings still remain usable.
    if not chapters:
        chapters = [c for c in fallback_documents if len(c["text"]) >= 20]

    # Remove exact duplicate chapters introduced by malformed spines.
    unique, seen = [], set()
    for chapter in chapters:
        signature = (_norm_space(chapter["title"]).lower(),
                     _norm_space(chapter["text"])[:500].lower())
        if signature in seen:
            report["noise_blocks_removed"] += 1
            continue
        seen.add(signature)
        unique.append(chapter)
    chapters = unique

    if max_chars and max_chars > 0:
        chapters = _enforce_max_chars(chapters, max_chars)
    chapters = [c for c in chapters if c["text"].strip()]
    report["chapters_detected"] = len(chapters)
    report.update(_validate_chapter_sequence(chapters))
    LAST_CLEAN_REPORT = report
    return chapters


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
    """Convert MOBI/AZW/FB2/HTML/RTF to EPUB, then use the same cleaner."""
    if not shutil.which("ebook-convert"):
        raise RuntimeError(
            "Dinh dang nay can calibre (ebook-convert). Hay cai calibre trong workflow."
        )
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tf:
        out_epub = tf.name
    try:
        subprocess.run(
            ["ebook-convert", path, out_epub, "--enable-heuristics"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return parse_epub(out_epub, max_chars)
    finally:
        if os.path.exists(out_epub):
            os.remove(out_epub)


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
    ap.add_argument(
        "--start",
        type=int,
        default=1,
        help="Chuong bat dau (1-based). Vi du --start 5 -> bo qua 4 chuong dau.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Chi lay toi da N chuong ke tu --start (0 = lay het). Dung de tranh qua tai.",
    )
    ap.add_argument(
        "--probe",
        action="store_true",
        help="Chi DEM so chuong (khong ghi file), in JSON ra stdout roi thoat.",
    )
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print("Loi: khong tim thay file %r" % args.input, file=sys.stderr)
        sys.exit(1)

    chapters = parse_ebook(args.input, args.max_chars)
    if not chapters:
        print("Loi: khong trich xuat duoc noi dung nao", file=sys.stderr)
        sys.exit(2)

    total_all = len(chapters)

    # Che do PROBE: chi dem so chuong (khong ghi file) de bot hoi nguoi dung
    # muon tao bao nhieu chuong, tranh gui ca cuon mot luc gay qua tai.
    if args.probe:
        probe = {
            "count": total_all,
            "chapters": [
                {"index": i, "title": c["title"][:200], "chars": len(c["text"])}
                for i, c in enumerate(chapters, start=1)
            ],
            "cleaning": LAST_CLEAN_REPORT,
        }
        print(json.dumps(probe, ensure_ascii=False))
        return

    # Cat lay khoang chuong mong muon (start 1-based; limit = so chuong, 0 = het).
    start = max(1, args.start)
    selected = chapters[start - 1:]
    if args.limit and args.limit > 0:
        selected = selected[: args.limit]
    if not selected:
        print(
            "Loi: khoang chuong khong hop le (start=%d, limit=%d, tong=%d)"
            % (args.start, args.limit, total_all),
            file=sys.stderr,
        )
        sys.exit(2)
    chapters = selected

    os.makedirs(args.out_dir, exist_ok=True)

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

    if LAST_CLEAN_REPORT:
        with open(os.path.join(args.out_dir, "cleaning_report.json"), "w", encoding="utf-8") as f:
            json.dump(LAST_CLEAN_REPORT, f, ensure_ascii=False, indent=2)

    total = sum(m["chars"] for m in manifest)
    scope = ""
    if args.start > 1 or (args.limit and args.limit > 0):
        scope = " (chon %d/%d chuong, bat dau tu chuong %d)" % (
            len(manifest), total_all, max(1, args.start),
        )
    print("\nHoan tat: %d chuong, tong %d ky tu -> %s%s" % (len(manifest), total, args.out_dir, scope))


if __name__ == "__main__":
    main()
