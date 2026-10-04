"""One-off repair for databases seeded before the GDELT switch.

    python -m app.demo.migrate_news

- Google News RSS sources (disallowed by robots.txt) -> GDELT news API sources.
- Removes pricing sources for sites that refuse automated access (HTTP 405).
- Removes price rows whose "plan" is pricing-page chrome (e.g. "Custom", "User").
"""

import asyncio

from sqlalchemy import delete, select

from app.agents.nodes.change_detection import is_plausible_plan_name
from app.db.base import utcnow
from app.db.models import PricePoint, Source
from app.db.session import system_session
from app.monitoring.fetchers.feeds import gdelt_url


async def main() -> None:
    async with system_session() as db:
        news = (
            (await db.execute(select(Source).where(Source.url.like("https://news.google.com/%"))))
            .scalars()
            .all()
        )
        for s in news:
            query = (s.config or {}).get("query") or s.name
            s.url = gdelt_url(query)
            s.name = "News (GDELT)"
            s.etag = s.last_modified = s.last_error = None
            s.consecutive_failures = 0
            s.last_status = None
            s.next_check_at = utcnow()
        blocked = (
            (
                await db.execute(
                    select(Source).where(Source.source_type == "pricing", Source.last_error.like("HTTP 405%"))
                )
            )
            .scalars()
            .all()
        )
        for s in blocked:
            await db.delete(s)
        junk = [
            p.id
            for p in (await db.execute(select(PricePoint))).scalars()
            if not is_plausible_plan_name(p.plan)
        ]
        if junk:
            await db.execute(delete(PricePoint).where(PricePoint.id.in_(junk)))
        # Retry pricing pages that timed out under the old browser wait strategy.
        timed_out = (
            (await db.execute(select(Source).where(Source.last_error.like("Rendering failed%"))))
            .scalars()
            .all()
        )
        for s in timed_out:
            s.consecutive_failures, s.last_error, s.next_check_at = 0, None, utcnow()
        await db.commit()
    print(
        f"news sources -> GDELT: {len(news)}; blocked pricing sources removed: {len(blocked)}; "
        f"junk price rows removed: {len(junk)}; timed-out pages re-queued: {len(timed_out)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
