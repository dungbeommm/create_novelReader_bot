"""A tiny, extensible rule engine for text normalization.

A :class:`Rule` is just a named callable ``str -> str``. The :class:`RuleEngine`
applies rules in order. New rules can be added programmatically or via dotted
import paths in configuration, satisfying the "easy to extend" requirement
without touching the core code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module

from ..utils.logging import get_logger

logger = get_logger(__name__)

RuleFunc = Callable[[str], str]


@dataclass(slots=True)
class Rule:
    """A single named normalization step."""

    name: str
    func: RuleFunc

    def apply(self, text: str) -> str:
        return self.func(text)


class RuleEngine:
    """Ordered collection of rules applied sequentially."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self._rules: list[Rule] = rules or []

    def add(self, rule: Rule) -> "RuleEngine":
        self._rules.append(rule)
        return self

    def extend_from_paths(self, dotted_paths: list[str]) -> "RuleEngine":
        """Load extra rules from ``module:function`` dotted paths."""
        for path in dotted_paths:
            module_name, _, attr = path.partition(":")
            if not attr:
                module_name, _, attr = path.rpartition(".")
            func = getattr(import_module(module_name), attr)
            self.add(Rule(name=path, func=func))
            logger.info("Loaded custom normalization rule: %s", path)
        return self

    def run(self, text: str) -> str:
        for rule in self._rules:
            text = rule.apply(text)
        return text

    @property
    def names(self) -> list[str]:
        return [rule.name for rule in self._rules]
