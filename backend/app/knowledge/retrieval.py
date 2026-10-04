"""Hybrid retrieval over competitive memory: pgvector cosine similarity + Postgres full-text,
fused with reciprocal-rank fusion (RRF)."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KBChunk, Snapshot, Source
from app.llm.client import get_llm

RRF_K = 60


async def hybrid_search(
    db: AsyncSession,
    query: str,
    *,
    competitor_id: uuid.UUID | None = None,
    kinds: list[str] | None = None,
    exclude_ref_ids: list[uuid.UUID] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []

    def _filters(stmt):
        if competitor_id:
            stmt = stmt.where(KBChunk.competitor_id == competitor_id)
        if kinds:
            stmt = stmt.where(KBChunk.kind.in_(kinds))
        if exclude_ref_ids:
            stmt = stmt.where(KBChunk.ref_id.not_in(exclude_ref_ids))
        return stmt

    ranked: dict[uuid.UUID, dict[str, Any]] = {}

    vectors = await get_llm().embed([query])
    if vectors:
        dist = KBChunk.embedding.cosine_distance(vectors[0])
        stmt = _filters(
            select(KBChunk, dist.label("dist"))
            .where(KBChunk.embedding.is_not(None))
            .order_by(dist)
            .limit(limit * 3)
        )
        for rank, (chunk, d) in enumerate((await db.execute(stmt)).all()):
            entry = ranked.setdefault(chunk.id, {"chunk": chunk, "score": 0.0})
            entry["score"] += 1.0 / (RRF_K + rank)
            entry["similarity"] = round(1 - float(d), 4)

    tsq = func.websearch_to_tsquery("english", query)
    rank_expr = func.ts_rank_cd(KBChunk.tsv, tsq)
    stmt = _filters(
        select(KBChunk, rank_expr.label("r"))
        .where(KBChunk.tsv.op("@@")(tsq))
        .order_by(rank_expr.desc())
        .limit(limit * 3)
    )
    for rank, (chunk, _r) in enumerate((await db.execute(stmt)).all()):
        entry = ranked.setdefault(chunk.id, {"chunk": chunk, "score": 0.0})
        entry["score"] += 1.0 / (RRF_K + rank)

    results = sorted(ranked.values(), key=lambda e: e["score"], reverse=True)[:limit]
    return [
        {
            "id": str(e["chunk"].id),
            "kind": e["chunk"].kind,
            "ref_id": str(e["chunk"].ref_id) if e["chunk"].ref_id else None,
            "competitor_id": str(e["chunk"].competitor_id) if e["chunk"].competitor_id else None,
            "title": e["chunk"].title,
            "content": e["chunk"].content,
            "meta": e["chunk"].meta,
            "occurred_at": e["chunk"].occurred_at.isoformat(),
            "score": round(e["score"], 5),
            "similarity": e.get("similarity"),
        }
        for e in results
    ]


async def search_monitored_sources(
    db: AsyncSession,
    query: str,
    *,
    exclude_source_id: uuid.UUID | None = None,
    competitor_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Full-text search across the latest snapshot of monitored sources (cross-source corroboration).
    With `competitor_id`, only that competitor's own sources plus general news feeds are searched."""
    latest = (
        select(Snapshot.id)
        .distinct(Snapshot.source_id)
        .order_by(Snapshot.source_id, Snapshot.fetched_at.desc())
        .subquery()
    )
    tsq = func.websearch_to_tsquery("english", query)
    rank_expr = func.ts_rank_cd(Snapshot.tsv, tsq)
    stmt = (
        select(Snapshot, Source, rank_expr.label("r"))
        .join(Source, Source.id == Snapshot.source_id)
        .where(Snapshot.id.in_(select(latest.c.id)), Snapshot.tsv.op("@@")(tsq))
        .order_by(rank_expr.desc())
        .limit(limit)
    )
    if exclude_source_id:
        stmt = stmt.where(Snapshot.source_id != exclude_source_id)
    if competitor_id:
        stmt = stmt.where(or_(Source.competitor_id == competitor_id, Source.source_type == "news"))
    rows = (await db.execute(stmt)).all()
    return [
        {
            "snapshot_id": str(s.id),
            "source_id": str(src.id),
            "url": src.url,
            "title": src.name,
            "text": s.text,
            "fetched_at": s.fetched_at.isoformat(),
            "items": s.structured.get("items", []),
        }
        for s, src, _ in rows
    ]
