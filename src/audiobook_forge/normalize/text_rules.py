"""General, language-independent normalization rules.

Each function is a pure ``str -> str`` transform so it can be unit tested and
composed in any order by the :class:`RuleEngine`.
"""

from __future__ import annotations

import html
import re
import unicodedata

_BBCODE = re.compile(r"\[/?[a-zA-Z][^\]]*\]")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~|`+)")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MULTISPACE = re.compile(r"[ \t\f\v\u00a0]+")
_MULTINEWLINE = re.compile(r"\n{3,}")
_DOTS = re.compile(r"\.{3,}")
_ELLIPSIS = "\u2026"

# Emoji + pictographic symbol ranges.
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\U00002190-\U000021ff"
    "\U0000fe00-\U0000fe0f"
    "\U0001f000-\U0001f0ff"
    "]+",
    flags=re.UNICODE,
)

# Map fancy punctuation to speech-friendly ASCII-ish equivalents.
_PUNCT_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u00b7": ".", "\u2022": ".",
    "\u3001": ",", "\u3002": ".", "\uff0c": ",", "\uff0e": ".",
    "\uff01": "!", "\uff1f": "?", "\uff1a": ":", "\uff1b": ";",
}
_PUNCT_TABLE = {ord(k): v for k, v in _PUNCT_MAP.items()}


def unicode_normalize(text: str, form: str = "NFC") -> str:
    """Apply a Unicode normalization form (default NFC)."""
    return unicodedata.normalize(form, text)


def decode_html_entities(text: str) -> str:
    """Turn ``&amp;`` / ``&#233;`` etc. into real characters."""
    return html.unescape(text)


def strip_markdown(text: str) -> str:
    """Remove common Markdown markup, keeping link/image alt text."""
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_BLOCKQUOTE.sub("", text)
    text = _MD_EMPHASIS.sub("", text)
    return text


def strip_bbcode(text: str) -> str:
    """Remove ``[b]...[/b]``-style BBCode tags."""
    return _BBCODE.sub("", text)


def remove_emoji(text: str) -> str:
    """Drop emoji and pictographic symbols that TTS cannot read."""
    return _EMOJI.sub("", text)


def normalize_punctuation(text: str) -> str:
    """Fold smart quotes, dashes and full-width punctuation; unify ellipses."""
    text = text.replace(_ELLIPSIS, "...")
    text = text.translate(_PUNCT_TABLE)
    text = _DOTS.sub("...", text)
    return text


def collapse_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs and limit blank lines to at most one."""
    text = _MULTISPACE.sub(" ", text)
    text = _MULTINEWLINE.sub("\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()
