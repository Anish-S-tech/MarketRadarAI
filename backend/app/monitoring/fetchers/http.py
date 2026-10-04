from dataclasses import dataclass, field

import httpx

from app.config import settings


class FetchError(Exception):
    def __init__(self, reason: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status


@dataclass
class HttpResult:
    url: str
    status: int
    content: bytes = b""
    content_type: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    not_modified: bool = False

    @property
    def text(self) -> str:
        return self.content.decode(_charset(self.content_type), errors="replace")


def _charset(content_type: str) -> str:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip() or "utf-8"
    return "utf-8"


def make_client(user_agent: str | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": user_agent or settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8",
        },
        timeout=settings.fetch_timeout_seconds,
        follow_redirects=True,
        max_redirects=5,
    )


async def fetch_http(
    client: httpx.AsyncClient, url: str, *, etag: str | None = None, last_modified: str | None = None
) -> HttpResult:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 304:
                return HttpResult(
                    url=str(resp.url), status=304, not_modified=True, headers=dict(resp.headers)
                )
            if resp.status_code >= 400:
                raise FetchError("http_status", f"HTTP {resp.status_code} for {url}", resp.status_code)
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > settings.fetch_max_bytes:
                    raise FetchError("too_large", f"Response exceeds {settings.fetch_max_bytes} bytes")
                chunks.append(chunk)
            return HttpResult(
                url=str(resp.url),
                status=resp.status_code,
                content=b"".join(chunks),
                content_type=resp.headers.get("content-type", ""),
                headers=dict(resp.headers),
            )
    except httpx.TimeoutException as e:
        raise FetchError("timeout", f"Timeout fetching {url}") from e
    except httpx.HTTPError as e:
        raise FetchError("network", f"{type(e).__name__}: {e}") from e
