"""One-off: re-sync every competitor's pricing history from its latest pricing snapshot.

    python -m app.cli_backfill

Idempotent — sync_price_points only opens/closes rows when a plan's price actually differs.
"""

import asyncio

from sqlalchemy import select

from app.db.models import Snapshot, Source
from app.db.session import system_session, tenant_session
from app.knowledge import kb_service


async def main() -> None:
    async with system_session() as db:
        sources = [
            (s.org_id, s.id, s.competitor_id, s.name)
            for s in (await db.execute(select(Source).where(Source.source_type == "pricing"))).scalars()
        ]
    for org_id, source_id, competitor_id, name in sources:
        async with tenant_session(org_id) as db:
            snap = (
                await db.execute(
                    select(Snapshot)
                    .where(Snapshot.source_id == source_id)
                    .order_by(Snapshot.fetched_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            plans = (snap.structured.get("pricing") or {}).get("plans", []) if snap else []
            if not snap or not plans:
                continue
            result = await kb_service.sync_price_points(
                db, org_id, competitor_id, plans, snapshot_id=snap.id, observed_at=snap.fetched_at
            )
            await db.commit()
            print(f"{source_id} {name}: {result}")


if __name__ == "__main__":
    asyncio.run(main())
