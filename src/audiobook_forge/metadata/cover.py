"""Cover-art handling: reuse an embedded cover or synthesize a clean one."""

from __future__ import annotations

from pathlib import Path

from ..utils.logging import get_logger

logger = get_logger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional
    Image = None  # type: ignore[assignment]

_BG = (30, 41, 59)
_FG = (226, 232, 240)
_ACCENT = (99, 102, 241)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}".strip()
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:6]


def generate_cover(title: str, author: str, dst: Path, size: int = 1400) -> Path:
    """Render a simple, tasteful cover when the ebook has none."""
    if Image is None:
        raise RuntimeError("Pillow is required to generate covers.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (size, size), _BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size, 18], fill=_ACCENT)
    draw.rectangle([0, size - 18, size, size], fill=_ACCENT)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 84)
        author_font = ImageFont.truetype("DejaVuSans.ttf", 52)
    except OSError:  # pragma: no cover - font fallback
        title_font = ImageFont.load_default()
        author_font = ImageFont.load_default()

    y = size // 3
    for line in _wrap(title, 18):
        draw.text((90, y), line, font=title_font, fill=_FG)
        y += 104
    if author:
        draw.text((90, y + 40), author, font=author_font, fill=_ACCENT)
    img.save(dst, "JPEG", quality=90)
    logger.info("Generated cover: %s", dst)
    return dst


def ensure_cover(existing: str | None, title: str, author: str, dst: Path) -> Path | None:
    """Return a usable cover path: reuse the embedded one or generate a new one."""
    if existing and Path(existing).exists():
        return Path(existing)
    try:
        return generate_cover(title, author, dst)
    except Exception as exc:  # pragma: no cover - non-fatal
        logger.warning("Could not generate cover: %s", exc)
        return None
