"""Vietnamese text expansion so Piper reads naturally.

Converts numbers, dates, times, currency, percentages, common units,
abbreviations, emails and URLs into spoken Vietnamese words instead of letting
Piper spell them out character by character.

The implementation is intentionally rule-based and dependency-free so it runs
fast on low-resource GitHub runners.
"""

from __future__ import annotations

import re

_DIGITS = ["kh\u00f4ng", "m\u1ed9t", "hai", "ba", "b\u1ed1n", "n\u0103m", "s\u00e1u", "b\u1ea3y", "t\u00e1m", "ch\u00edn"]
_UNITS = ["", "ngh\u00ecn", "tri\u1ec7u", "t\u1ef7"]

_MONTHS = {
    1: "m\u1ed9t", 2: "hai", 3: "ba", 4: "t\u01b0", 5: "n\u0103m", 6: "s\u00e1u",
    7: "b\u1ea3y", 8: "t\u00e1m", 9: "ch\u00edn", 10: "m\u01b0\u1eddi", 11: "m\u01b0\u1eddi m\u1ed9t", 12: "m\u01b0\u1eddi hai",
}

# Spoken forms for common units and symbols.
_UNIT_WORDS = {
    "km": "ki l\u00f4 m\u00e9t", "cm": "x\u0103ng ti m\u00e9t", "mm": "mi li m\u00e9t",
    "m": "m\u00e9t", "kg": "ki l\u00f4 gam", "g": "gam", "mg": "mi li gam",
    "kb": "ki l\u00f4 b\u00e1i", "mb": "m\u00ea ga b\u00e1i", "gb": "gi ga b\u00e1i", "tb": "t\u00ea ra b\u00e1i",
    "km/h": "ki l\u00f4 m\u00e9t tr\u00ean gi\u1edd", "kmh": "ki l\u00f4 m\u00e9t tr\u00ean gi\u1edd",
    "ml": "mi li l\u00edt", "l": "l\u00edt", "kwh": "ki l\u00f4 o\u00e1t gi\u1edd",
}

_CURRENCY = {
    "\u20ab": "\u0111\u1ed3ng", "vnd": "\u0111\u1ed3ng", "vn\u0111": "\u0111\u1ed3ng",
    "$": "\u0111\u00f4 la", "usd": "\u0111\u00f4 la", "\u20ac": "\u01a1 r\u00f4", "eur": "\u01a1 r\u00f4",
    "\u00a3": "b\u1ea3ng", "\u00a5": "y\u00ean",
}

_ABBREVIATIONS = {
    "tp": "th\u00e0nh ph\u1ed1", "tp.": "th\u00e0nh ph\u1ed1", "tt": "th\u1ecb tr\u1ea5n",
    "q.": "qu\u1eadn", "p.": "ph\u01b0\u1eddng", "tx": "th\u1ecb x\u00e3",
    "ubnd": "\u1ee7y ban nh\u00e2n d\u00e2n", "hdnd": "h\u1ed9i \u0111\u1ed3ng nh\u00e2n d\u00e2n",
    "ts": "ti\u1ebfn s\u0129", "ths": "th\u1ea1c s\u0129", "gs": "gi\u00e1o s\u01b0", "pgs": "ph\u00f3 gi\u00e1o s\u01b0",
    "bs": "b\u00e1c s\u0129", "vs": "\u0111\u1ea5u v\u1edbi", "tr": "trang",
}


def _read_three_digits(number: int) -> str:
    hundreds, remainder = divmod(number, 100)
    tens, units = divmod(remainder, 10)
    words: list[str] = []
    if hundreds:
        words.append(f"{_DIGITS[hundreds]} tr\u0103m")
    if tens == 0:
        if units and hundreds:
            words.append("linh")
        if units:
            words.append(_DIGITS[units])
    elif tens == 1:
        words.append("m\u01b0\u1eddi")
        if units == 5:
            words.append("l\u0103m")
        elif units:
            words.append(_DIGITS[units])
    else:
        words.append(f"{_DIGITS[tens]} m\u01b0\u01a1i")
        if units == 1:
            words.append("m\u1ed1t")
        elif units == 5:
            words.append("l\u0103m")
        elif units:
            words.append(_DIGITS[units])
    return " ".join(words)


def read_integer(number: int) -> str:
    """Read a non-negative integer as Vietnamese words."""
    if number == 0:
        return _DIGITS[0]
    if number < 0:
        return "\u00e2m " + read_integer(-number)

    groups: list[int] = []
    while number > 0:
        number, rem = divmod(number, 1000)
        groups.append(rem)

    parts: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        group = groups[i]
        if group == 0:
            continue
        chunk = _read_three_digits(group)
        unit = _UNITS[i] if i < len(_UNITS) else _UNITS[-1] * i
        parts.append(f"{chunk} {unit}".strip())
    return " ".join(parts).strip()


def _read_number_token(token: str) -> str:
    """Read a numeric token that may contain grouping/decimal separators."""
    token = token.replace(".", "").replace(",", ".") if token.count(",") == 1 else token.replace(".", "")
    if "." in token:
        whole, _, frac = token.partition(".")
        whole_words = read_integer(int(whole)) if whole else _DIGITS[0]
        frac_words = " ".join(_DIGITS[int(d)] for d in frac if d.isdigit())
        return f"{whole_words} ph\u1ea9y {frac_words}"
    return read_integer(int(token)) if token.isdigit() else token


def expand_numbers(text: str) -> str:
    """Expand standalone integers/decimals into words."""
    return re.sub(r"\d[\d.,]*", lambda m: _read_number_token(m.group(0)), text)


def expand_dates(text: str) -> str:
    """Expand ``dd/mm/yyyy`` and ``dd/mm`` into spoken dates."""

    def repl(match: re.Match[str]) -> str:
        day, month = int(match.group(1)), int(match.group(2))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return match.group(0)
        out = f"ng\u00e0y {read_integer(day)} th\u00e1ng {_MONTHS[month]}"
        if match.group(3):
            out += f" n\u0103m {read_integer(int(match.group(3)))}"
        return out

    return re.sub(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b", repl, text)


def expand_times(text: str) -> str:
    """Expand ``HH:MM`` into ``H gi\u1edd M ph\u00fat``."""

    def repl(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return match.group(0)
        out = f"{read_integer(hour)} gi\u1edd"
        if minute:
            out += f" {read_integer(minute)} ph\u00fat"
        return out

    return re.sub(r"\b(\d{1,2}):(\d{2})\b", repl, text)


def expand_currency(text: str) -> str:
    """Expand amounts with a currency symbol/code into spoken currency."""
    pattern = re.compile(
        r"([\d.,]+)\s?(\u20ab|\$|\u20ac|\u00a3|\u00a5|vn\u0111|vnd|usd|eur)",
        re.IGNORECASE,
    )

    def repl(match: re.Match[str]) -> str:
        amount = _read_number_token(match.group(1))
        unit = _CURRENCY.get(match.group(2).lower(), match.group(2))
        return f"{amount} {unit}"

    return pattern.sub(repl, text)


def expand_percent(text: str) -> str:
    """Expand ``50%`` -> ``n\u0103m m\u01b0\u01a1i ph\u1ea7n tr\u0103m``."""
    return re.sub(
        r"([\d.,]+)\s?%",
        lambda m: f"{_read_number_token(m.group(1))} ph\u1ea7n tr\u0103m",
        text,
    )


def expand_units(text: str) -> str:
    """Expand ``100km`` -> ``m\u1ed9t tr\u0103m ki l\u00f4 m\u00e9t`` and similar units."""
    keys = sorted(_UNIT_WORDS, key=len, reverse=True)
    pattern = re.compile(rf"([\d.,]+)\s?({'|'.join(re.escape(k) for k in keys)})\b", re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        amount = _read_number_token(match.group(1))
        unit = _UNIT_WORDS[match.group(2).lower()]
        return f"{amount} {unit}"

    return pattern.sub(repl, text)


def expand_email_url(text: str) -> str:
    """Make emails/URLs readable (``@`` -> ``a c\u00f2ng``, ``.`` -> ``ch\u1ea5m``)."""
    text = re.sub(
        r"https?://\S+",
        lambda m: "\u0111\u01b0\u1eddng d\u1eabn " + _spell_url(m.group(0)),
        text,
    )
    text = re.sub(
        r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
        lambda m: _spell_email(m.group(0)),
        text,
    )
    return text


def _spell_email(email: str) -> str:
    local, _, domain = email.partition("@")
    domain_spoken = domain.replace(".", " ch\u1ea5m ")
    return f"{local} a c\u00f2ng {domain_spoken}"


def _spell_url(url: str) -> str:
    url = re.sub(r"^https?://", "", url).rstrip("/")
    return url.replace(".", " ch\u1ea5m ").replace("/", " g\u1ea1ch ch\u00e9o ")


def expand_abbreviations(text: str) -> str:
    """Expand common Vietnamese abbreviations (case-insensitive, word-bounded)."""
    def repl(match: re.Match[str]) -> str:
        word = match.group(0)
        return _ABBREVIATIONS.get(word.lower(), word)

    keys = sorted(_ABBREVIATIONS, key=len, reverse=True)
    pattern = re.compile(rf"(?<!\w)({'|'.join(re.escape(k) for k in keys)})(?!\w)", re.IGNORECASE)
    return pattern.sub(repl, text)


def normalize_vietnamese(text: str) -> str:
    """Full Vietnamese expansion pipeline, ordered to avoid conflicts.

    Order matters: structured tokens (dates, times, currency, percent, units,
    email/url) are expanded before bare numbers so their digits are not consumed
    prematurely.
    """
    text = expand_email_url(text)
    text = expand_abbreviations(text)
    text = expand_dates(text)
    text = expand_times(text)
    text = expand_currency(text)
    text = expand_percent(text)
    text = expand_units(text)
    text = expand_numbers(text)
    return text
