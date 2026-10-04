import asyncio
import sys

if sys.platform == "win32":  # pragma: no cover - local Windows development only
    # psycopg (LangGraph checkpointer) cannot run on the default Proactor event loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
