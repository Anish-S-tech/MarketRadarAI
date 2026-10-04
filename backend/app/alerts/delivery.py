"""Delivery channels: in-app (Redis pub/sub -> SSE) and email (SMTP)."""

import json
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib
import markdown as md
import redis.asyncio as aioredis
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

PRIORITY_COLORS = {"critical": "#c62828", "high": "#e8710a", "medium": "#1a73e8", "low": "#5f6368"}


def user_channel(user_id: uuid.UUID | str) -> str:
    return f"alerts:user:{user_id}"


async def publish_in_app(user_id: uuid.UUID, payload: dict[str, Any]) -> None:
    try:
        r = aioredis.from_url(settings.redis_url)
        try:
            await r.publish(user_channel(user_id), json.dumps(payload, default=str))
        finally:
            await r.aclose()
    except Exception as e:  # the alert is persisted either way; realtime push is best-effort
        log.warning("inapp.publish_failed", error=str(e)[:200])


def md_to_html(text: str) -> str:
    return md.markdown(text, extensions=["tables", "sane_lists"])


def render_email(*, title: str, kicker: str, body_md: str, priority: str = "medium") -> str:
    return templates.get_template("email.html.j2").render(
        title=title,
        kicker=kicker,
        body_html=md_to_html(body_md),
        accent=PRIORITY_COLORS.get(priority, "#1a73e8"),
        settings_link=f"{settings.frontend_url}/settings",
    )


async def send_email(to: str, subject: str, html: str, text: str) -> None:
    if not settings.email_enabled:
        raise RuntimeError("email disabled")
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_starttls,
        timeout=30,
    )
