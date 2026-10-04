"""Test configuration. Environment is set before any `app` import so settings pick it up."""

import os

os.environ.update(
    {
        "ENV": "test",
        "LOG_JSON": "false",
        "LLM_PROVIDER": "fake",
        "S3_ENABLED": "false",
        "PER_DOMAIN_MIN_INTERVAL_SECONDS": "0",
        "RESPECT_ROBOTS": "false",
        "PLAYWRIGHT_ENABLED": "false",
        "ALLOW_PRIVATE_SOURCES": "true",
        "SEARXNG_URL": "http://searxng.test",
        "REDIS_URL": "redis://127.0.0.1:1/0",  # unreachable on purpose: realtime/throttle must degrade gracefully
        "EMAIL_ENABLED": "true",
    }
)

import asyncio  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def event_loop_policy():
    # psycopg (LangGraph checkpointer) needs a selector loop on Windows.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
