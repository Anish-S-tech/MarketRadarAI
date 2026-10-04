"""Scout Agent: collects the current state of a monitored source and maintains historical snapshots."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.agents.tracing import traced
from app.db.base import utcnow
from app.db.models import Competitor, Snapshot, Source
from app.db.session import tenant_session
from app.monitoring.collector import SourceSpec, collect
from app.monitoring.fetchers.http import FetchError
from app.monitoring.storage import put_blob

MAX_BACKOFF_MINUTES = 24 * 60


async def latest_snapshot(db, source_id: uuid.UUID) -> Snapshot | None:
    return (
        await db.execute(
            select(Snapshot)
            .where(Snapshot.source_id == source_id)
            .order_by(Snapshot.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@traced("scout")
async def scout_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    source_id = uuid.UUID(state["source_id"])

    async with tenant_session(org_id) as db:
        source = await db.get(Source, source_id)
        if source is None:
            return {"scout_status": "error", "errors": [f"source {source_id} not found"]}
        competitor = await db.get(Competitor, source.competitor_id)
        spec = SourceSpec(
            id=str(source.id),
            source_type=source.source_type,
            url=source.url,
            render_js=source.render_js,
            include_selectors=source.include_selectors,
            ignore_selectors=source.ignore_selectors,
            config=source.config,
            etag=source.etag,
            last_modified=source.last_modified,
            competitor_name=competitor.name if competitor else "",
            competitor_cik=competitor.cik if competitor else None,
        )
        interval = source.check_interval_minutes

    now = utcnow()
    try:
        collected = await collect(spec)
    except FetchError as e:
        async with tenant_session(org_id) as db:
            source = await db.get(Source, source_id)
            assert source is not None
            source.consecutive_failures += 1
            backoff = min(MAX_BACKOFF_MINUTES, interval * (2 ** min(source.consecutive_failures, 6)))
            source.last_checked_at = now
            source.next_check_at = now + timedelta(minutes=backoff)
            source.last_status = "error"
            source.last_error = str(e)[:2000]
            await db.commit()
            
        if e.reason == "rate_limited" or e.status == 429:
            return {
                "scout_status": "not_modified",
                "_summary": {"reason": "rate_limited"}
            }
        
        return {
            "scout_status": "error",
            "errors": [f"fetch failed ({e.reason}): {e}"],
            "_summary": {"error": str(e)[:300], "reason": e.reason},
        }

    async with tenant_session(org_id) as db:
        source = await db.get(Source, source_id)
        assert source is not None
        prev = await latest_snapshot(db, source_id)
        source.last_checked_at = now
        source.next_check_at = now + timedelta(minutes=interval)
        source.consecutive_failures = 0
        source.last_error = None
        if collected.etag:
            source.etag = collected.etag
        if collected.last_modified:
            source.last_modified = collected.last_modified

        if collected.not_modified or (prev and prev.content_hash == collected.content_hash):
            source.last_status = "unchanged"
            await db.commit()
            status = "not_modified" if collected.not_modified else "unchanged"
            return {
                "scout_status": status,
                "snapshot_id": str(prev.id) if prev else None,
                "_summary": {"status": status, "method": collected.fetch_method},
            }

        snap_id = uuid.uuid4()
        ext = "json" if collected.raw_content_type == "application/json" else "html"
        blob_key = await put_blob(
            f"{org_id}/{source_id}/{now:%Y%m%dT%H%M%S}_{snap_id.hex[:8]}.{ext}",
            collected.raw,
            collected.raw_content_type,
        )
        snap = Snapshot(
            id=snap_id,
            org_id=org_id,
            source_id=source_id,
            content_hash=collected.content_hash,
            text=collected.text,
            title=collected.title[:500],
            structured=collected.structured,
            blob_key=blob_key,
            http_status=collected.http_status,
            fetch_method=collected.fetch_method,
            fetched_at=now,
        )
        db.add(snap)
        status = "changed" if prev else "first_snapshot"
        source.last_status = status
        await db.commit()

    return {
        "scout_status": status,
        "snapshot_id": str(snap_id),
        "prev_snapshot_id": str(prev.id) if prev else None,
        "_summary": {
            "status": status,
            "method": collected.fetch_method,
            "chars": len(collected.text),
            "items": len(collected.structured.get("items", [])),
        },
    }
