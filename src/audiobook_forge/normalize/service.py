"""Assembles the normalization rule engine from settings."""

from __future__ import annotations

from functools import partial

from ..config.models import NormalizationSettings
from . import text_rules as tr
from .base import Rule, RuleEngine
from .vietnamese import normalize_vietnamese


class NormalizationService:
    """Builds and runs a :class:`RuleEngine` configured from settings.

    The order of rules is deliberate: markup/entities are stripped first, then
    Unicode is normalized, then language-specific expansion runs on clean text,
    and whitespace collapsing happens last.
    """

    def __init__(self, settings: NormalizationSettings) -> None:
        self._settings = settings
        self._engine = self._build_engine(settings)

    @staticmethod
    def _build_engine(cfg: NormalizationSettings) -> RuleEngine:
        engine = RuleEngine()
        if cfg.decode_html_entities:
            engine.add(Rule("html_entities", tr.decode_html_entities))
        if cfg.strip_markdown:
            engine.add(Rule("markdown", tr.strip_markdown))
        if cfg.strip_bbcode:
            engine.add(Rule("bbcode", tr.strip_bbcode))
        engine.add(Rule("unicode", partial(tr.unicode_normalize, form=cfg.unicode_form)))
        if cfg.remove_emoji:
            engine.add(Rule("emoji", tr.remove_emoji))
        if cfg.normalize_punctuation:
            engine.add(Rule("punctuation", tr.normalize_punctuation))
        if cfg.language == "vi" and cfg.expand_vietnamese:
            engine.add(Rule("vietnamese", normalize_vietnamese))
        if cfg.collapse_whitespace:
            engine.add(Rule("whitespace", tr.collapse_whitespace))
        if cfg.extra_rules:
            engine.extend_from_paths(cfg.extra_rules)
        return engine

    def normalize(self, text: str) -> str:
        """Normalize a block of text using the configured rule chain."""
        return self._engine.run(text)

    @property
    def rule_names(self) -> list[str]:
        return self._engine.names
