#!/usr/bin/env python3
"""Generates the fictional competitor websites served by the `demo-sites` container and applies
scenario mutations so you can watch the agents detect, research, verify, analyse and alert.

    python scripts/demo_mutate.py reset              # baseline sites
    python scripts/demo_mutate.py acme-price-hike    # Acme raises Growth price, announces it on blog + newswire
    python scripts/demo_mutate.py globex-partnership # Globex partners with Snowflake, launches Globex Connect
    python scripts/demo_mutate.py initech-launch     # Initech launches Copilot add-on
    python scripts/demo_mutate.py noise              # cosmetic-only edit (should NOT alert)
    python scripts/demo_mutate.py status

Sites are served at http://<site>.localtest.me:8090 (*.localtest.me resolves to 127.0.0.1; inside Docker the
same hostnames are network aliases of the demo-sites container).
"""

import copy
import json
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

UTC = timezone.utc

ROOT = Path(__file__).resolve().parent.parent / "deploy" / "demo-sites"
PUBLIC = ROOT / "public"
STATE = ROOT / "state.json"
PORT = 8090

BASELINE = {
    "acme": {
        "name": "Acme Insights",
        "tagline": "Self-serve analytics for fast-moving teams",
        "plans": [
            {"name": "Starter", "price": 29, "features": ["5 dashboards", "Daily data refresh", "Email support"]},
            {"name": "Growth", "price": 79, "features": ["Unlimited dashboards", "Hourly refresh", "SSO", "API access"]},
            {"name": "Enterprise", "price": None, "features": ["Dedicated CSM", "Audit logs", "Custom SLAs"]},
        ],
        "posts": [
            {"title": "How Acme customers cut reporting time in half", "days_ago": 20,
             "body": "Case study: three customers describe their analytics workflows with Acme Insights."},
            {"title": "Acme Insights Q2 product recap", "days_ago": 45,
             "body": "Scheduled exports, new chart types and faster queries shipped this quarter."},
        ],
        "changelog": [
            "2026-08-30 — Faster dashboard loading for large workspaces",
            "2026-08-12 — New funnel chart type",
        ],
        "features_page": [],
    },
    "globex": {
        "name": "Globex Data",
        "tagline": "The governed data platform for the modern enterprise",
        "plans": [
            {"name": "Team", "price": 49, "features": ["10 users", "Data catalog", "Community support"]},
            {"name": "Business", "price": 129, "features": ["50 users", "Lineage", "Role-based access"]},
            {"name": "Enterprise", "price": None, "features": ["Unlimited users", "Private cloud", "24/7 support"]},
        ],
        "posts": [
            {"title": "Why data governance matters in 2026", "days_ago": 12,
             "body": "Governance is becoming a board-level topic. Here is how Globex helps."},
        ],
        "changelog": [],
        "features_page": [
            "Globex Catalog — find and trust every dataset",
            "Globex Lineage — column-level lineage across your stack",
        ],
    },
    "initech": {
        "name": "Initech Cloud",
        "tagline": "Embedded analytics for SaaS products",
        "plans": [
            {"name": "Developer", "price": 0, "features": ["1 app", "Community support"]},
            {"name": "Pro", "price": 99, "features": ["5 apps", "White-labeling", "Email support"]},
            {"name": "Scale", "price": 399, "features": ["Unlimited apps", "Multi-tenant row-level security", "Priority support"]},
        ],
        "posts": [
            {"title": "Initech Cloud achieves SOC 2 Type II", "days_ago": 30,
             "body": "Initech Cloud completed its SOC 2 Type II audit with zero exceptions."},
        ],
        "changelog": [],
        "features_page": [],
    },
    "newswire": {
        "name": "TechNewswire",
        "posts": [
            {"title": "Analytics market expected to grow 18% in 2027", "days_ago": 5,
             "body": "Analysts expect continued consolidation in the BI and analytics market."},
        ],
    },
    "noise_counter": 0,
}


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else copy.deepcopy(BASELINE)


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))
    render(state)


def page(title: str, body: str, footer_note: str = "") -> str:
    year = datetime.now(UTC).year
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{font-family:system-ui;max-width:900px;margin:40px auto;padding:0 16px;color:#222}}
.plan{{border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0}}.price{{font-size:1.4em;font-weight:600}}</style>
</head><body>
<nav><a href="/">Home</a> · <a href="/pricing.html">Pricing</a> · <a href="/blog/">Blog</a></nav>
<main>
{body}
</main>
<footer>© {year} {escape(title.split(' — ')[0])}. All rights reserved. {escape(footer_note)}</footer>
</body></html>
"""


def slug_for(title: str) -> str:
    return "post-" + hashlib.md5(title.encode()).hexdigest()[:10]


def price_str(p) -> str:
    return "Contact sales" if p is None else f"${p:g} / month"


def render_pricing(site: dict) -> str:
    plans = "\n".join(
        f"""<section class="plan"><h3>{escape(p['name'])}</h3>
<p class="price">{price_str(p['price'])}</p>
<ul>{''.join(f'<li>✓ {escape(f)}</li>' for f in p['features'])}</ul></section>"""
        for p in site["plans"]
    )
    return page(f"{site['name']} — Pricing", f"<h1>Pricing</h1>\n<p>{escape(site['tagline'])}</p>\n{plans}")


def render_rss(site_key: str, site: dict) -> str:
    now = datetime.now(UTC)
    items = []
    for i, post in enumerate(site["posts"]):
        slug = slug_for(post["title"])
        pub = format_datetime(now - timedelta(days=post.get("days_ago", 0), minutes=i))
        items.append(f"""<item><title>{escape(post['title'])}</title>
<link>http://{site_key}.localtest.me:{PORT}/blog/{slug}.html</link><guid>{slug}</guid>
<pubDate>{pub}</pubDate><description>{escape(post['body'])}</description></item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{escape(site['name'])} Blog</title>
<link>http://{site_key}.localtest.me:{PORT}/</link><description>News from {escape(site['name'])}</description>
{''.join(items)}
</channel></rss>
"""


def render_post_pages(site_key: str, site: dict, out: Path) -> None:
    (out / "blog").mkdir(parents=True, exist_ok=True)
    for post in site["posts"]:
        slug = slug_for(post["title"])
        (out / "blog" / f"{slug}.html").write_text(
            page(f"{site['name']} — {post['title']}", f"<article><h1>{escape(post['title'])}</h1><p>{escape(post['body'])}</p></article>"),
            encoding="utf-8",
        )


def render(state: dict) -> None:
    for key in ("acme", "globex", "initech"):
        site = state[key]
        out = PUBLIC / key
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(page(site["name"], f"<h1>{escape(site['name'])}</h1><p>{escape(site['tagline'])}</p>"), encoding="utf-8")
        (out / "pricing.html").write_text(render_pricing(site), encoding="utf-8")
        (out / "blog").mkdir(exist_ok=True)
        (out / "blog" / "rss.xml").write_text(render_rss(key, site), encoding="utf-8")
        render_post_pages(key, site, out)
        changelog = "".join(f"<li>{escape(c)}</li>" for c in site["changelog"])
        noise = f"Page build {state.get('noise_counter', 0)}"
        (out / "changelog.html").write_text(page(f"{site['name']} — Changelog", f"<h1>Changelog</h1><ul>{changelog}</ul>", noise), encoding="utf-8")
        features = "".join(f"<h2>{escape(f.split(' — ')[0])}</h2><p>{escape(f)}</p>" for f in site["features_page"])
        (out / "product.html").write_text(page(f"{site['name']} — Product", f"<h1>Product</h1><p>{escape(site['tagline'])}</p>{features}", noise), encoding="utf-8")
    nw = state["newswire"]
    out = PUBLIC / "newswire"
    out.mkdir(parents=True, exist_ok=True)
    (out / "rss.xml").write_text(render_rss("newswire", nw), encoding="utf-8")
    render_post_pages("newswire", nw, out)
    (out / "index.html").write_text(page("TechNewswire", "<h1>TechNewswire</h1>"), encoding="utf-8")


def plan(site: dict, name: str) -> dict:
    return next(p for p in site["plans"] if p["name"] == name)


def acme_price_hike(s: dict) -> None:
    acme = s["acme"]
    plan(acme, "Growth")["price"] = 99
    plan(acme, "Starter")["features"].append("AI-generated summaries")
    acme["posts"].insert(0, {"title": "New Growth plan pricing: more AI, now $99 per month", "days_ago": 0,
                             "body": "Starting today the Acme Insights Growth plan costs $99 per month (previously $79), "
                                     "and every plan now includes AI-generated summaries."})
    s["newswire"]["posts"].insert(0, {"title": "Acme Insights raises Growth plan price to $99 amid AI push", "days_ago": 0,
                                      "body": "Acme Insights increased the price of its Growth plan from $79 to $99 per month, "
                                              "citing new AI-generated summaries included in all plans."})


def globex_partnership(s: dict) -> None:
    g = s["globex"]
    g["posts"].insert(0, {"title": "Globex partners with Snowflake to launch Globex Connect", "days_ago": 0,
                          "body": "Globex Data announced a strategic partnership with Snowflake and launched Globex Connect, "
                                  "a native connector that brings Globex governance to Snowflake workloads."})
    g["features_page"].append("Globex Connect — native Snowflake integration with governance built in")
    g["tagline"] = "The governed data platform for the AI-ready enterprise"


def initech_launch(s: dict) -> None:
    i = s["initech"]
    i["posts"].insert(0, {"title": "Initech launches Initech Copilot, an AI analyst for embedded dashboards", "days_ago": 0,
                          "body": "Initech Cloud launched Initech Copilot, letting end users ask questions of embedded "
                                  "dashboards in natural language. Copilot is available as an add-on for $15 per user per month."})
    i["plans"].insert(2, {"name": "Copilot add-on", "price": 15, "features": ["Natural-language questions", "AI chart builder"]})


def noise(s: dict) -> None:
    s["noise_counter"] = s.get("noise_counter", 0) + 1


SCENARIOS = {
    "acme-price-hike": acme_price_hike,
    "globex-partnership": globex_partnership,
    "initech-launch": initech_launch,
    "noise": noise,
}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "reset":
        save(copy.deepcopy(BASELINE))
        print("Demo sites reset to baseline.")
    elif cmd in SCENARIOS:
        state = load()
        SCENARIOS[cmd](state)
        save(state)
        print(f"Applied scenario '{cmd}'. Trigger a check (UI 'Check now' or wait for the scheduler).")
    elif cmd == "status":
        state = load()
        for key in ("acme", "globex", "initech"):
            prices = ", ".join(f"{p['name']}={price_str(p['price'])}" for p in state[key]["plans"])
            print(f"{state[key]['name']}: {prices}; posts={len(state[key]['posts'])}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
