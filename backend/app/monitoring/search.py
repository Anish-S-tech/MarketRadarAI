"""Web and news search for the Research Agent (self-hosted SearXNG + Google News RSS; no API keys)."""

import re

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.monitoring.fetchers.feeds import gdelt_url, parse_gdelt
from app.monitoring.politeness import domain_throttle

log = get_logger(__name__)


async def searxng_search(client: httpx.AsyncClient, query: str, limit: int = 5) -> list[dict]:
    if not settings.searxng_url:
        return []
    try:
        r = await client.get(
            f"{settings.searxng_url.rstrip('/')}/search",
            params={"q": query, "format": "json", "language": "en"},
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except (httpx.HTTPError, ValueError) as e:
        log.warning("search.searxng_failed", query=query, error=str(e)[:200])
        return []
    return [
        {
            "url": x.get("url", ""),
            "title": x.get("title", ""),
            "content": x.get("content", ""),
            "published": x.get("publishedDate"),
            "origin": "web",
        }
        for x in results[:limit]
        if x.get("url")
    ]


async def news_search(client: httpx.AsyncClient, query: str, limit: int = 5) -> list[dict]:
    try:
        url = gdelt_url(query, timespan="30d", maxrecords=limit)
        await domain_throttle(url)
        r = await client.get(url, timeout=20)
        r.raise_for_status()
        items = parse_gdelt(r.content)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 429:
            log.warning("search.news_failed", query=query, error=str(e)[:200])
        return []
    except Exception as e:
        log.warning("search.news_failed", query=query, error=str(e)[:200])
        return []
    return [
        {
            "url": i["url"],
            "title": i["title"],
            "content": i.get("summary", ""),
            "published": i.get("published"),
            "origin": "news",
        }
        for i in items[:limit]
    ]


_STOP = set(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "it",
        "its",
        "at",
        "as",
        "from",
    ]
)


def _toks(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9$%.]+", s.lower()) if t not in _STOP and len(t) > 1}


def best_passage(text: str, claims: list[str], window: int = 1200) -> str:
    """Return the window of `text` with the highest token overlap with the claims."""
    if len(text) <= window:
        return text
    target = set().union(*(_toks(c) for c in claims)) if claims else set()
    if not target:
        return text[:window]
    paras = [p for p in re.split(r"\n+", text) if p.strip()]
    best, best_score = text[:window], -1.0
    for i in range(len(paras)):
        chunk = ""
        for p in paras[i:]:
            if len(chunk) + len(p) > window:
                break
            chunk += p + "\n"
        score = len(_toks(chunk) & target)
        if score > best_score:
            best, best_score = chunk or paras[i][:window], score
    return best.strip()
