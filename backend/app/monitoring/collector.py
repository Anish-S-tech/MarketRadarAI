"""Source collection: fetch -> extract -> normalise, per source type."""

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.core.telemetry import FETCH_ERRORS, FETCH_LATENCY
from app.db.enums import SourceType
from app.monitoring.extract import extract_text
from app.monitoring.fetchers.browser import fetch_rendered
from app.monitoring.fetchers.feeds import fetch_edgar, is_gdelt, parse_gdelt, parse_rss, parse_sitemap
from app.monitoring.fetchers.http import FetchError, fetch_http, make_client
from app.monitoring.netsafety import assert_public_url
from app.monitoring.normalize import content_hash, normalize_text
from app.monitoring.politeness import domain_throttle, robots_allows


@dataclass
class SourceSpec:
    """Plain-data view of a Source row (decoupled from the ORM session)."""

    id: str
    source_type: str
    url: str
    render_js: bool = False
    include_selectors: list[str] = field(default_factory=list)
    ignore_selectors: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    etag: str | None = None
    last_modified: str | None = None
    competitor_name: str = ""
    competitor_cik: str | None = None


@dataclass
class Collected:
    not_modified: bool = False
    title: str = ""
    text: str = ""
    content_hash: str = ""
    structured: dict[str, Any] = field(default_factory=dict)
    raw: bytes = b""
    raw_content_type: str = "text/html"
    http_status: int | None = None
    fetch_method: str = "http"
    etag: str | None = None
    last_modified: str | None = None
    final_url: str = ""


def looks_js_rendered(html: str, text: str) -> bool:
    """Heuristic: very little text, or little text on a script-heavy page (SPA shell)."""
    if len(text) < 80:
        return True
    return len(text) < settings.min_text_chars_before_browser and html.lower().count("<script") >= 3


def _items_text(items: list[dict]) -> str:
    return "\n".join(f"{i['title']} | {i.get('summary', '')[:300]}".strip() for i in items)


async def collect(spec: SourceSpec) -> Collected:
    st = SourceType(spec.source_type)
    t0 = time.perf_counter()
    method = "http"
    try:
        await assert_public_url(spec.url)
        async with make_client() as client:
            if st == SourceType.sec_filing:
                # EDGAR's JSON API is the sanctioned programmatic access path (UA with contact required).
                cik = spec.config.get("cik") or spec.competitor_cik
                if not cik:
                    raise FetchError(
                        "config", "SEC source requires a CIK (source.config.cik or competitor.cik)"
                    )
                method = "edgar"
                await domain_throttle("https://data.sec.gov/")
                items = await fetch_edgar(client, cik)
                return _feed_result(items, method)

            if not await robots_allows(spec.url, client):
                raise FetchError("robots", f"robots.txt disallows {spec.url}")
            await domain_throttle(spec.url)

            res = await fetch_http(client, spec.url, etag=spec.etag, last_modified=spec.last_modified)
            if res.not_modified:
                return Collected(not_modified=True, http_status=304, fetch_method="http")

            if st in (SourceType.blog_rss, SourceType.news):
                if is_gdelt(spec.url):
                    method = "gdelt"
                    items = parse_gdelt(res.content)
                else:
                    method = "rss"
                    items = parse_rss(res.content)
                out = _feed_result(items, method)
            elif st == SourceType.sitemap:
                method = "sitemap"
                out = _feed_result(parse_sitemap(res.content), method)
            else:
                html = res.text
                mode = "full" if st == SourceType.pricing else "article"
                ex = extract_text(
                    html,
                    include_selectors=spec.include_selectors,
                    ignore_selectors=spec.ignore_selectors,
                    mode=mode,
                )
                needs_browser = spec.render_js or looks_js_rendered(html, ex.text)
                if needs_browser and settings.playwright_enabled:
                    try:
                        html = await fetch_rendered(spec.url, spec.config.get("wait_selector"))
                        ex = extract_text(
                            html,
                            include_selectors=spec.include_selectors,
                            ignore_selectors=spec.ignore_selectors,
                            mode=mode,
                        )
                        method = "browser"
                    except FetchError:
                        if spec.render_js:
                            raise
                text = normalize_text(ex.text, spec.config.get("ignore_patterns"))
                out = Collected(
                    title=ex.title,
                    text=text,
                    content_hash=content_hash(text),
                    raw=html.encode(),
                    fetch_method=method,
                )
            out.http_status = res.status
            out.etag = res.headers.get("etag")
            out.last_modified = res.headers.get("last-modified")
            out.final_url = res.url
            return out
    except FetchError as e:
        FETCH_ERRORS.labels(st.value, e.reason).inc()
        raise
    except Exception as e:
        FETCH_ERRORS.labels(st.value, "unexpected").inc()
        raise FetchError("unexpected", f"{type(e).__name__}: {e}") from e
    finally:
        FETCH_LATENCY.labels(st.value, method).observe(time.perf_counter() - t0)


def _feed_result(items: list[dict], method: str) -> Collected:
    import json

    text = _items_text(items)
    # Hash only on item identity so feed reordering / summary tweaks don't count as changes.
    ids = sorted(i["id"] for i in items)
    return Collected(
        title="feed",
        text=text,
        content_hash=content_hash("\n".join(ids)),
        structured={"items": items},
        raw=json.dumps(items).encode(),
        raw_content_type="application/json",
        fetch_method=method,
    )


async def quick_fetch_text(client: httpx.AsyncClient, url: str, max_chars: int = 6000) -> tuple[str, str]:
    """Best-effort article fetch for research evidence. Returns (title, text)."""
    await assert_public_url(url)
    res = await fetch_http(client, url)
    if "html" not in res.content_type and "xml" not in res.content_type and res.content_type:
        return "", ""
    ex = extract_text(res.text, mode="article")
    return ex.title, normalize_text(ex.text)[:max_chars]
