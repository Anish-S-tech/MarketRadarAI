"""HTML -> clean text extraction."""

from dataclasses import dataclass

import trafilatura
from selectolax.parser import HTMLParser

ALWAYS_STRIP = ["script", "style", "noscript", "svg", "iframe", "template", "link", "meta"]
CHROME_STRIP = [
    "nav",
    "footer",
    "header",
    "[role=navigation]",
    "[aria-hidden=true]",
    ".cookie",
    "#cookie-banner",
]


@dataclass
class Extracted:
    title: str
    text: str


def _node_text(node) -> str:
    return node.text(separator="\n", strip=True)


def extract_text(
    html: str,
    *,
    include_selectors: list[str] | None = None,
    ignore_selectors: list[str] | None = None,
    mode: str = "article",  # article | full
) -> Extracted:
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else ""

    for sel in ALWAYS_STRIP + list(ignore_selectors or []):
        for n in tree.css(sel):
            n.decompose()

    if include_selectors:
        parts = [_node_text(n) for sel in include_selectors for n in tree.css(sel)]
        return Extracted(title=title, text="\n".join(p for p in parts if p))

    if mode == "article":
        extracted = trafilatura.extract(
            tree.html or html,
            include_tables=True,
            include_comments=False,
            favor_recall=True,
            output_format="txt",
        )
        if extracted and len(extracted) > 200:
            return Extracted(title=title, text=extracted)

    for sel in CHROME_STRIP:
        for n in tree.css(sel):
            n.decompose()
    body = tree.body
    return Extracted(title=title, text=_node_text(body) if body else "")
