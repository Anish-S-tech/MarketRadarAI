"""robots.txt compliance and per-domain rate limiting (shared across workers via Redis)."""

import asyncio
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
_robots_cache: dict[str, tuple[float, RobotFileParser | None]] = {}
ROBOTS_TTL = 6 * 3600


async def robots_allows(url: str, client: httpx.AsyncClient) -> bool:
    if not settings.respect_robots:
        return True
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    cached = _robots_cache.get(base)
    if not cached or time.time() - cached[0] > ROBOTS_TTL:
        rp: RobotFileParser | None = RobotFileParser()
        try:
            r = await client.get(f"{base}/robots.txt", timeout=10)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())  # type: ignore[union-attr]
            else:
                rp = None  # no robots.txt -> allowed
        except httpx.HTTPError:
            rp = None
        _robots_cache[base] = (time.time(), rp)
        cached = _robots_cache[base]
    rp = cached[1]
    return True if rp is None else rp.can_fetch(settings.user_agent, url)


async def domain_throttle(url: str) -> None:
    """Ensure a minimum interval between hits to the same domain across all workers."""
    domain = urlparse(url).netloc
    seconds = settings.per_domain_min_interval_overrides.get(domain, settings.per_domain_min_interval_seconds)
    if settings.per_domain_min_interval_seconds <= 0:  # throttling disabled entirely (tests)
        return
    interval_ms = int(seconds * 1000)
    if interval_ms <= 0:
        return
    try:
        r = aioredis.from_url(settings.redis_url)
        try:
            for _ in range(60):
                if await r.set(f"throttle:{domain}", "1", px=interval_ms, nx=True):
                    return
                ttl = await r.pttl(f"throttle:{domain}")
                await asyncio.sleep(max(ttl, 100) / 1000)
        finally:
            await r.aclose()
    except Exception as e:  # Redis down -> don't block monitoring
        log.warning("throttle.redis_unavailable", error=str(e)[:200])
