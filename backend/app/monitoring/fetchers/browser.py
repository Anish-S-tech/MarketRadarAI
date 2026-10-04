"""Headless Chromium rendering for JS-heavy pages (pricing calculators, SPAs)."""

from app.config import settings
from app.core.logging import get_logger
from app.monitoring.fetchers.http import FetchError

log = get_logger(__name__)


async def fetch_rendered(url: str, wait_selector: str | None = None) -> str:
    if not settings.playwright_enabled:
        raise FetchError("browser_disabled", "Playwright rendering is disabled")
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:  # api image ships without browsers
        raise FetchError("browser_unavailable", "Playwright not installed") from e

    try:
        pw_cm = async_playwright()
        pw = await pw_cm.__aenter__()
    except Exception as e:  # e.g. no subprocess support on this event loop / platform
        raise FetchError("browser_unavailable", f"Playwright start failed: {type(e).__name__}: {e}") from e
    try:
        try:
            browser = await pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
        except Exception as e:
            raise FetchError("browser_unavailable", f"Chromium launch failed: {e}") from e
        try:
            ctx = await browser.new_context(user_agent=settings.user_agent, java_script_enabled=True)
            page = await ctx.new_page()
            # Skip heavy assets; we only need the rendered DOM text.
            await page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in {"image", "media", "font"}
                    else route.continue_()
                ),
            )
            # "networkidle" never fires on many marketing sites (analytics beacons, chat widgets keep the
            # network busy), so wait for the DOM, then give client-side rendering a bounded settle window.
            await page.goto(
                url, wait_until="domcontentloaded", timeout=int(settings.fetch_timeout_seconds * 1000)
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                await page.wait_for_timeout(2_000)
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=10_000)
            return await page.content()
        except FetchError:
            raise
        except Exception as e:
            raise FetchError("browser_error", f"Rendering failed: {e}") from e
        finally:
            await browser.close()
    finally:
        await pw_cm.__aexit__(None, None, None)
