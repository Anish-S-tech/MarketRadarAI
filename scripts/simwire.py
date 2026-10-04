#!/usr/bin/env python3
"""SimWire — a local, clearly-labelled SIMULATED news wire for the BI-market demo.

Real competitors (Power BI, Tableau, Looker, Qlik, ThoughtSpot, Domo) are seeded with real history by
`python -m app.cli seed-market`. SimWire supplies plausible *simulated* developments so the agents have
something recent to detect. Every item says it is simulated, and events from this feed are flagged
`is_simulated` and badged "Simulated" throughout the product.

    python scripts/simwire.py reset            # feeds with only older background items (agents take a baseline)
    python scripts/simwire.py release all      # publish every scenario
    python scripts/simwire.py release tableau  # publish one competitor's scenario
    python scripts/simwire.py status

Served at http://simwire.localtest.me:8090/<slug>.xml by the demo-sites container.
"""

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "deploy" / "demo-sites"
OUT = ROOT / "public" / "simwire"
STATE = ROOT / "simwire_state.json"
BASE = "http://simwire.localtest.me:8090"
LABEL = "SIMULATED — demo scenario, not real news."

# Background items (published as the baseline; the agents record them without alerting).
BACKGROUND = {
    "powerbi": [("Power BI community webinar recap: modelling best practices", 21),
                ("Customer story: a retailer consolidates reporting on Power BI", 35)],
    "tableau": [("Tableau community recap: highlights from recent user groups", 18),
                ("Customer story: a hospital network tracks capacity with Tableau", 40)],
    "looker": [("Looker tips: organising LookML projects for large teams", 25),
               ("Customer story: a media company standardises metrics in Looker", 44)],
    "qlik": [("Qlik partner spotlight: regional systems integrators", 20),
             ("Customer story: a manufacturer monitors supply chains with Qlik", 38)],
    "thoughtspot": [("ThoughtSpot webinar recap: search-driven analytics for sales teams", 16),
                    ("Customer story: a fintech embeds ThoughtSpot in its product", 33)],
    "domo": [("Domo user group recap: building executive dashboards", 22),
             ("Customer story: a franchise chain unifies store data in Domo", 41)],
}

# Plausible simulated developments — one per competitor.
SCENARIOS = {
    "powerbi": ("Microsoft adds Copilot to every Power BI Pro licence at no extra cost",
                "Microsoft says Copilot in Power BI, previously tied to Fabric capacity, will be included with all "
                "Power BI Pro and Premium Per User licences from next quarter, with no change to the $14 Pro price."),
    "tableau": ("Tableau introduces a Starter plan at $35 per user per month for small teams",
                "Tableau announced Tableau Starter, a cloud plan for teams of up to 10 users at $35 per user per "
                "month, combining Creator-level authoring with Tableau Pulse, aimed at small and mid-sized businesses."),
    "looker": ("Google bundles Looker Studio Pro with Google Workspace Enterprise plans",
               "Google will include Looker Studio Pro in Google Workspace Enterprise Standard and Plus plans, "
               "adding team workspaces and Gemini-assisted report building for Workspace customers."),
    "qlik": ("Qlik and Databricks announce joint go-to-market for open lakehouse analytics",
             "Qlik and Databricks announced a joint go-to-market partnership pairing Qlik Talend Cloud data "
             "integration and Qlik Cloud Analytics with the Databricks Data Intelligence Platform."),
    "thoughtspot": ("ThoughtSpot cuts Essentials plan price by 20% to target mid-market buyers",
                    "ThoughtSpot reduced the list price of its Essentials analytics plan by 20% and raised its user "
                    "limit, a move the company says targets mid-market teams evaluating Power BI and Tableau."),
    "domo": ("Domo launches a free plan for teams of up to five users",
             "Domo introduced a free plan for teams of up to five users with limited credits, positioning it as "
             "an entry point to its consumption-based pricing for larger deployments."),
}

NAMES = {"powerbi": "Microsoft Power BI", "tableau": "Tableau", "looker": "Looker", "qlik": "Qlik",
         "thoughtspot": "ThoughtSpot", "domo": "Domo"}


def _id(slug: str, title: str) -> str:
    return f"sim-{slug}-" + hashlib.md5(title.encode()).hexdigest()[:10]


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"released": {}}


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))
    render(state)


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{escape(title)} — SimWire</title>"
            "<style>body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px}"
            ".sim{background:#f3e8ff;color:#6b21a8;padding:8px 12px;border-radius:8px;font-weight:600}</style>"
            f"</head><body><p class='sim'>{LABEL}</p><article><h1>{escape(title)}</h1><p>{escape(body)}</p>"
            "</article></body></html>")


def render(state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    for slug in NAMES:
        entries = [(t, f"{NAMES[slug]}: {t.lower()}.", now - timedelta(days=d)) for t, d in BACKGROUND[slug]]
        if slug in state["released"]:
            title, body = SCENARIOS[slug]
            entries.insert(0, (title, body, datetime.fromisoformat(state["released"][slug])))
        (OUT / slug).mkdir(exist_ok=True)
        items = []
        for title, body, when in entries:
            iid = _id(slug, title)
            (OUT / slug / f"{iid}.html").write_text(page(title, body), encoding="utf-8")
            items.append(
                f"<item><title>{escape(title)}</title><link>{BASE}/{slug}/{iid}.html</link><guid>{iid}</guid>"
                f"<pubDate>{format_datetime(when)}</pubDate>"
                f"<description>{escape(body)} ({LABEL})</description></item>"
            )
        (OUT / f"{slug}.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            f"<title>SimWire (SIMULATED) — {escape(NAMES[slug])}</title><link>{BASE}/</link>"
            f"<description>{LABEL}</description>{''.join(items)}</channel></rss>\n",
            encoding="utf-8",
        )
    (OUT / "index.html").write_text(page("SimWire", "Simulated competitor news for the MarketRadar demo."), encoding="utf-8")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    state = load()
    if cmd == "reset":
        save({"released": {}})
        print("SimWire reset: background items only. Let the agents take a baseline, then run `release all`.")
    elif cmd == "release":
        target = sys.argv[2] if len(sys.argv) > 2 else "all"
        slugs = list(SCENARIOS) if target == "all" else [target]
        for slug in slugs:
            if slug not in SCENARIOS:
                sys.exit(f"unknown competitor '{slug}'; choose from: {', '.join(SCENARIOS)}")
            state["released"].setdefault(slug, datetime.now(timezone.utc).isoformat())
        save(state)
        print(f"Released simulated scenario(s): {', '.join(slugs)}")
    elif cmd == "status":
        for slug, (title, _) in SCENARIOS.items():
            print(f"{'RELEASED ' if slug in state['released'] else 'pending  '} {NAMES[slug]}: {title}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
