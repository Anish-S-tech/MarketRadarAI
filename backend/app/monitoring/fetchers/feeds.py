"""Feed-style sources: RSS/Atom (blogs, press feeds), SEC EDGAR filings, GDELT news and sitemaps.
All return a uniform list of items: {id, title, url, summary, published}."""

import hashlib
import json
import re
from datetime import UTC, datetime
from time import mktime
from urllib.parse import quote_plus
from xml.etree import ElementTree

import feedparser
import httpx

from app.config import settings
from app.monitoring.extract import extract_text
from app.monitoring.fetchers.http import FetchError


def _item_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()[:20]


def _clean_html(s: str) -> str:
    if "<" not in s:
        return s.strip()
    return extract_text(f"<html><body>{s}</body></html>", mode="full").text.strip()


def parse_rss(content: bytes | str) -> list[dict]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise FetchError("parse", f"Invalid feed: {feed.bozo_exception}")
    items = []
    for e in feed.entries[:100]:
        published = None
        tp = e.get("published_parsed") or e.get("updated_parsed")
        if tp:
            published = datetime.fromtimestamp(mktime(tp), tz=UTC).isoformat()
        link = e.get("link", "")
        items.append(
            {
                "id": e.get("id") or _item_id(link, e.get("title", "")),
                "title": _clean_html(e.get("title", ""))[:500],
                "url": link,
                "summary": _clean_html(e.get("summary", "") or e.get("description", ""))[:4000],
                "published": published,
            }
        )
    return items


# News comes from the GDELT DOC 2.0 API, which is built for programmatic access (no robots.txt restrictions;
# it asks for at most one request per 5 seconds, which the per-domain throttle enforces). Google News RSS
# search is disallowed for bots by its robots.txt, so it is deliberately not used.
GDELT_HOST = "api.gdeltproject.org"


def gdelt_url(query: str, timespan: str = "3d", maxrecords: int = 25) -> str:
    return (
        f"https://{GDELT_HOST}/api/v2/doc/doc?format=json&mode=artlist&sort=datedesc"
        f"&maxrecords={maxrecords}&timespan={timespan}&query={quote_plus(query)}"
    )


def is_gdelt(url: str) -> bool:
    return url.startswith(f"https://{GDELT_HOST}/")


def parse_gdelt(content: bytes | str) -> list[dict]:
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    stripped = text.strip()
    if not stripped.startswith("{"):
        # GDELT answers rate limiting and bad queries with plain text. Treat it as a failed fetch, not an empty
        # feed — otherwise the next successful fetch would make every article look new.
        raise FetchError(
            "rate_limited" if "limit requests" in stripped.lower() else "parse", f"GDELT: {stripped[:200]}"
        )
    try:
        data = json.loads(stripped)
    except ValueError as e:
        raise FetchError("parse", f"GDELT returned invalid JSON: {e}") from e
    items = []
    for a in data.get("articles", []):
        if not a.get("url"):
            continue
        items.append(
            {
                "id": _item_id(a["url"]),
                "title": (a.get("title") or "")[:500],
                "url": a["url"],
                "summary": f"{a.get('domain', '')} · {a.get('language', '')} · {a.get('sourcecountry', '')}",
                "published": a.get("seendate"),
            }
        )
    return items


EDGAR_FORMS = {"10-K", "10-Q", "8-K", "S-1", "DEF 14A", "20-F", "6-K"}


async def fetch_edgar(client: httpx.AsyncClient, cik: str) -> list[dict]:
    cik10 = re.sub(r"\D", "", cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    try:
        r = await client.get(url, headers={"User-Agent": settings.sec_user_agent}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise FetchError("edgar", f"EDGAR fetch failed: {e}") from e
    recent = data.get("filings", {}).get("recent", {})
    items = []
    for i, form in enumerate(recent.get("form", [])[:80]):
        if form not in EDGAR_FORMS:
            continue
        acc = recent["accessionNumber"][i]
        doc = recent.get("primaryDocument", [""])[i]
        link = f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{acc.replace('-', '')}/{doc}"
        desc = recent.get("primaryDocDescription", [""])[i] or form
        items.append(
            {
                "id": acc,
                "title": f"{data.get('name', '')} filed {form}: {desc}",
                "url": link,
                "summary": f"Form {form} filed {recent['filingDate'][i]}. Items: {recent.get('items', [''])[i]}",
                "published": recent["filingDate"][i],
                "form": form,
            }
        )
    return items


def parse_sitemap(content: bytes) -> list[dict]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as e:
        raise FetchError("parse", f"Invalid sitemap: {e}") from e
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    items = []
    for u in root.findall("s:url", ns)[:5000]:
        loc = (u.findtext("s:loc", default="", namespaces=ns) or "").strip()
        lastmod = u.findtext("s:lastmod", default=None, namespaces=ns)
        if loc:
            slug = loc.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
            items.append({"id": loc, "title": slug.title(), "url": loc, "summary": "", "published": lastmod})
    return items
