import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.enums import Role, SourceType
from app.db.models import Competitor, Snapshot, Source
from app.deps import Principal, get_db, get_principal, require_roles
from app.monitoring.collector import SourceSpec, collect
from app.monitoring.fetchers.feeds import gdelt_url
from app.monitoring.fetchers.http import FetchError
from app.monitoring.netsafety import UnsafeURLError
from app.monitoring.storage import get_blob
from app.schemas.dto import (
    CheckQueued,
    SnapshotMeta,
    SnapshotOut,
    SourceIn,
    SourceOut,
    SourceTestIn,
    SourceTestOut,
    SourceUpdate,
)

router = APIRouter(prefix="/sources", tags=["sources"])
editor = Depends(require_roles(Role.executive, Role.product, Role.marketing, Role.pricing))


def _resolve_url(body: SourceIn, competitor: Competitor) -> str:
    if body.url:
        return body.url
    if body.source_type == SourceType.news:
        return gdelt_url(body.config.get("query") or f'"{competitor.name}"')
    if body.source_type == SourceType.sec_filing:
        cik = body.config.get("cik") or competitor.cik
        if not cik:
            raise HTTPException(422, "SEC sources need config.cik or a competitor CIK")
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    raise HTTPException(422, "url is required for this source type")


async def _get(db: AsyncSession, source_id: uuid.UUID) -> Source:
    s = await db.get(Source, source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    return s


@router.get("", response_model=list[SourceOut])
async def list_sources(competitor_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Source).order_by(Source.created_at)
    if competitor_id:
        stmt = stmt.where(Source.competitor_id == competitor_id)
    return list((await db.execute(stmt)).scalars())


@router.post("", response_model=SourceOut, status_code=201, dependencies=[editor])
async def create_source(
    body: SourceIn, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    competitor = await db.get(Competitor, body.competitor_id)
    if not competitor:
        raise HTTPException(404, "Competitor not found")
    data = body.model_dump()
    data["url"] = _resolve_url(body, competitor)
    data["source_type"] = body.source_type.value
    s = Source(org_id=p.org_id, next_check_at=utcnow(), **data)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@router.post("/test", response_model=SourceTestOut, dependencies=[editor])
async def test_source(body: SourceTestIn):
    """Fetch and extract a source once without saving anything (preview for the source editor)."""
    spec = SourceSpec(
        id="test",
        source_type=body.source_type.value,
        url=body.url,
        render_js=body.render_js,
        include_selectors=body.include_selectors,
        ignore_selectors=body.ignore_selectors,
        config=body.config,
    )
    try:
        c = await collect(spec)
    except (FetchError, UnsafeURLError) as e:
        return SourceTestOut(ok=False, error=str(e))
    return SourceTestOut(
        ok=True,
        title=c.title,
        text_preview=c.text[:4000],
        chars=len(c.text),
        items=c.structured.get("items", [])[:20],
        fetch_method=c.fetch_method,
    )


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await _get(db, source_id)


@router.patch("/{source_id}", response_model=SourceOut, dependencies=[editor])
async def update_source(source_id: uuid.UUID, body: SourceUpdate, db: AsyncSession = Depends(get_db)):
    s = await _get(db, source_id)
    data = body.model_dump(exclude_unset=True)
    if "url" in data and data["url"] != s.url:
        s.etag = s.last_modified = None
    for k, v in data.items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/{source_id}", status_code=204, dependencies=[editor])
async def delete_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    s = await _get(db, source_id)
    await db.delete(s)
    await db.commit()


@router.post("/{source_id}/check", response_model=CheckQueued, dependencies=[editor])
async def check_now(
    source_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    from app.workers.tasks import enqueue_source_check

    await _get(db, source_id)
    key = enqueue_source_check(p.org_id, source_id, trigger="manual")
    return CheckQueued(queued=True, idempotency_key=key)


@router.get("/{source_id}/snapshots", response_model=list[SnapshotMeta])
async def list_snapshots(
    source_id: uuid.UUID, limit: int = Query(50, le=500), db: AsyncSession = Depends(get_db)
):
    await _get(db, source_id)
    return list(
        (
            await db.execute(
                select(Snapshot)
                .where(Snapshot.source_id == source_id)
                .order_by(Snapshot.fetched_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


snap_router = APIRouter(prefix="/snapshots", tags=["sources"])


@snap_router.get("/{snapshot_id}", response_model=SnapshotOut)
async def get_snapshot(snapshot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    s = await db.get(Snapshot, snapshot_id)
    if not s:
        raise HTTPException(404, "Snapshot not found")
    return s


@snap_router.get("/{snapshot_id}/raw")
async def get_snapshot_raw(snapshot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    s = await db.get(Snapshot, snapshot_id)
    if not s or not s.blob_key:
        raise HTTPException(404, "Raw snapshot not available")
    data = await get_blob(s.blob_key)
    if data is None:
        raise HTTPException(404, "Raw snapshot not available")
    media = "application/json" if s.blob_key.endswith(".json") else "text/plain; charset=utf-8"
    # Served as text (never as HTML) so captured pages can't execute scripts in our origin.
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )
