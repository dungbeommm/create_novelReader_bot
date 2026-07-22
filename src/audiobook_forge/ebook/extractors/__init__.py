"""Concrete ebook extractors, one per family of formats."""

from __future__ import annotations

from .base import BaseExtractor
from .epub import EpubExtractor
from .fb2 import Fb2Extractor
from .html import HtmlExtractor
from .markdown import MarkdownExtractor
from .mobi import MobiExtractor
from .txt import TxtExtractor

#: Registry order matters: the first extractor whose ``supports`` returns True wins.
DEFAULT_EXTRACTORS: tuple[BaseExtractor, ...] = (
    EpubExtractor(),
    Fb2Extractor(),
    MarkdownExtractor(),
    HtmlExtractor(),
    MobiExtractor(),
    TxtExtractor(),
)

__all__ = [
    "BaseExtractor",
    "EpubExtractor",
    "Fb2Extractor",
    "HtmlExtractor",
    "MarkdownExtractor",
    "MobiExtractor",
    "TxtExtractor",
    "DEFAULT_EXTRACTORS",
]
