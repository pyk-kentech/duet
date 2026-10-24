"""mdlite: a CommonMark subset to HTML renderer (reference implementation)."""

from __future__ import annotations

from .blocks import BlockParser
from .html import HtmlRenderer

__all__ = ["render"]


def render(text: str) -> str:
    doc = BlockParser().parse(text)
    return HtmlRenderer().render(doc)
