"""Tests for the Vietnamese normalization layer."""

from __future__ import annotations

from audiobook_forge.normalize.vietnamese import normalize_vietnamese, read_integer


def test_read_integer_basic() -> None:
    assert read_integer(0) == "kh\u00f4ng"
    assert read_integer(5) == "n\u0103m"
    assert read_integer(15) == "m\u01b0\u1eddi l\u0103m"
    assert read_integer(21) == "hai m\u01b0\u01a1i m\u1ed1t"


def test_read_integer_hundreds_thousands() -> None:
    assert read_integer(100) == "m\u1ed9t tr\u0103m"
    assert "ngh\u00ecn" in read_integer(1000)


def test_units_km() -> None:
    out = normalize_vietnamese("100km")
    assert "ki l\u00f4 m\u00e9t" in out
    assert "m\u1ed9t tr\u0103m" in out


def test_percent() -> None:
    out = normalize_vietnamese("t\u0103ng 50%")
    assert "ph\u1ea7n tr\u0103m" in out


def test_currency() -> None:
    out = normalize_vietnamese("gi\u00e1 20.000\u0111")
    assert "\u0111\u1ed3ng" in out


def test_email_and_url_spoken() -> None:
    out = normalize_vietnamese("lien he a@b.com hoac https://x.com")
    assert "a c\u00f2ng b" in out or "c\u00f2ng" in out
