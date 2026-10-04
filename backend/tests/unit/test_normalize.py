from app.monitoring.normalize import block_diff, content_hash, normalize_text


def test_normalize_strips_noise_and_whitespace():
    raw = """
    Pricing   plans
    © 2026 Acme Inc.
    Accept cookies
    Updated 5 minutes ago
    Session a3f9c2e1b7d84f6a9c0e
    Growth $79 / month
    Growth $79 / month
    """
    out = normalize_text(raw)
    assert out.splitlines() == ["Pricing plans", "Acme Inc.", "Session", "Growth $79 / month"]


def test_hash_stable_under_noise():
    a = normalize_text("Plan A $10\n© 2025 Co")
    b = normalize_text("Plan A $10\n© 2026 Co")
    assert content_hash(a) == content_hash(b)


def test_block_diff_detects_modified_lines_and_ignores_moves():
    old = "Intro\nStarter $29\nGrowth $79\nFooter"
    new = "Intro\nGrowth $99\nStarter $29\nFooter"
    d = block_diff(old, new)
    assert d["added"] == ["Growth $99"]
    assert d["removed"] == ["Growth $79"]


def test_extra_ignore_patterns():
    out = normalize_text("Build 1234\nReal content", extra_ignore_patterns=[r"^Build \d+$"])
    assert out == "Real content"


def test_gdelt_rate_limit_is_a_failed_fetch_not_an_empty_feed():
    import pytest

    from app.monitoring.fetchers.feeds import gdelt_url, is_gdelt, parse_gdelt
    from app.monitoring.fetchers.http import FetchError

    url = gdelt_url('"Power BI"')
    assert is_gdelt(url) and "query=%22Power+BI%22" in url
    items = parse_gdelt(b'{"articles": [{"url": "https://x.com/a", "title": "T", "domain": "x.com"}]}')
    assert items[0]["url"] == "https://x.com/a" and items[0]["title"] == "T"
    with pytest.raises(FetchError) as e:
        parse_gdelt("Please limit requests to one every 5 seconds")
    assert e.value.reason == "rate_limited"
