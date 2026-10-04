from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def _key(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return f"org:{principal.org_id}:user:{principal.user_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_key,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url if settings.env != "test" else "memory://",
    headers_enabled=False,
    swallow_errors=True,  # never take the API down because Redis is unavailable
)
