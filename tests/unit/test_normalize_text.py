"""Tests for the generic text-normalization rule engine."""

from __future__ import annotations

from audiobook_forge.config.models import NormalizationSettings
from audiobook_forge.normalize.service import NormalizationService


def _svc(**overrides: object) -> NormalizationService:
    return NormalizationService(NormalizationSettings(**overrides))


def test_collapses_whitespace() -> None:
    out = _svc().normalize("Hello   world\n\n\n\nNext")
    assert "   " not in out
    assert "Hello world" in out


def test_strips_html_entities() -> None:
    out = _svc().normalize("Tom &amp; Jerry &lt;3")
    assert "&amp;" not in out
    assert "&" in out


def test_strips_markdown() -> None:
    out = _svc(strip_markdown=True).normalize("This is **bold** and _italic_ text")
    assert "**" not in out
    assert "_" not in out
    assert "bold" in out


def test_strips_bbcode() -> None:
    out = _svc(strip_bbcode=True).normalize("[b]hi[/b] [url=x]link[/url]")
    assert "[b]" not in out
    assert "[/b]" not in out


def test_strips_emoji() -> None:
    out = _svc(remove_emoji=True).normalize("Great book \U0001f600\U0001f680")
    assert "\U0001f600" not in out


def test_normalizes_ellipsis_and_quotes() -> None:
    out = _svc().normalize("He said\u2026 \u201cok\u201d")
    assert "\u2026" not in out
