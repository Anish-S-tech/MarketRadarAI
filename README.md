# MarketRadarAI

An agentic competitive-intelligence platform. It watches competitor websites, pricing pages, product pages, blogs, news and SEC filings **on its own schedule, without prompts**. It also:

- turns meaningful changes into **verified, prioritised, role-specific alerts**;
- writes a **daily intelligence brief** for each role;
- keeps a growing **competitive memory** of profiles, pricing history, products and relationships.

```
Celery beat ─► dispatch due sources (Postgres-driven schedule, jitter, per-domain politeness)
                 │
                 ▼
┌──────────────────────── LangGraph "intel_pipeline" (Postgres checkpoints, resumable) ────────────────────────┐
│ Scout ─► Change Detection ─┬─ nothing meaningful ─► END (snapshot kept)                                      │
│                            └─ per significant change (fan-out) ─► Research ─► Verification ─► Knowledge      │
│                                                                    │  └─ duplicate of known event ─► corroborate │
│                                                                    └► Impact ─► Prioritize ─► Alert          │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
Daily brief graph: gather ─► summarize (LLM) ─► compose per role ─► email
```

| Agent | What it does |
|---|---|
| **Scout** | Fetches each source: conditional GET via httpx, with a headless-Chromium fallback for JS pages. Handles RSS/Atom, news via the GDELT API, SEC EDGAR and sitemaps. Honours robots.txt, applies per-domain rate limits and SSRF guards, and backs off exponentially on failure. Normalises out noise (dates, nonces, cookie banners), stores the raw capture in S3 storage and keeps a snapshot history. |
| **Change Detection** | Diffs each snapshot against the previous one at block level. For pricing pages the LLM extracts a structured pricing table, which is diffed deterministically. Price moves are **grounded** in the text diff, which blocks moves the LLM invented. The LLM then classifies category and significance against a per-source threshold. |
| **Research** | Opens an event and generates claims and search queries. Gathers evidence from the competitor's own pages, its other monitored sources, the web (self-hosted SearXNG), news (GDELT) and the knowledge base. **Deduplicates** sightings of the same development, both lexically and semantically, so one move produces one alert. |
| **Verification** | The LLM judges every claim against every piece of evidence. A deterministic **grounding gate** then discards ungrounded "supports"/"contradicts" verdicts, which small models produce a lot. Confidence comes from an auditable formula: source reliability tier, independent domains, primary-source bonus, agreement and recency. That formula yields *Confirmed / Likely / Unverified / Disputed*. |
| **Knowledge** | Updates competitive memory: SCD-2 price history, products and features, relationships, and pgvector chunks for events and evidence. It also refreshes a rolling competitor profile. |
| **Impact** | Assesses the event against *our* company profile, products, pricing and segments. Outputs per-dimension severity, affected products and segments, implications for each role, and recommended actions. |
| **Prioritize** | Explainable weighted score (impact, threat tier, category, confidence, novelty) → **Low / Medium / High / Critical**. Guardrails stop shaky evidence from ever paging anyone at Critical. |
| **Alert** | Routes by subscription (role or personal × category × competitor × minimum priority). Renders a role-specific message: price tables for pricing, talking points for sales, and so on. Delivers in-app over SSE and by email; high and critical email immediately, the rest roll into the daily brief. Dedupes and throttles per user. |

Every agent step is recorded (latency, models used, inputs and outputs) and shown as a trace on each event. **The LLM decides what the evidence says; deterministic code decides how much to trust it and how urgent it is.** That split keeps the output reliable on small local models. If the LLM is unreachable, each task falls back to a heuristic so monitoring never stops.

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy 2 async, Alembic, Celery + Redis, LangGraph.
- **Database:** PostgreSQL 16 + pgvector (HNSW) + full-text search. Row-level security isolates tenants.
- **LLM:** local **Ollama**, with a separate classify model and reason model plus `nomic-embed-text` embeddings. Output is schema-constrained JSON, validated and retried. The provider is pluggable.
- **Frontend:** React 19 + TypeScript, Vite, Tailwind v4, TanStack Query, React Router, Recharts, React Flow. The API client is generated from OpenAPI.
- **Operations:** Docker Compose; Kubernetes (Kustomize: base plus dev/prod overlays with HPA and PDB); Prometheus + Grafana; OpenTelemetry; GitHub Actions CI with a Trivy scan.
- **Security:**
  - JWT access tokens plus rotating refresh tokens; optional OIDC SSO.
  - RBAC with roles admin, executive, product, sales, marketing and pricing.
  - Rate limiting, API keys, SSRF protection and security headers.

## Quick start (Docker)

Prerequisites: Docker, and [Ollama](https://ollama.com) running on the host.

```bash
cp .env.example .env
make models          # ollama pull llama3.2 && ollama pull nomic-embed-text
make up              # builds and starts everything; migrations run automatically
make seed            # demo org "Northwind Analytics" + 3 fictional competitors with 10 sources
```

| URL | What |
|---|---|
| http://localhost:8080 | App. Sign in as `admin@northwind.example.com` / `MarketRadar!2026` (users also exist for `ceo@`, `pm@`, `sales@`, `marketing@`, `pricing@`) |
| http://localhost:8000/api/docs | OpenAPI docs |
| http://localhost:8025 | Mailpit, which catches every alert and brief email |
| http://localhost:3000 | Grafana (`make observability`) |

### Watch the agents work

The demo competitors are real local websites (`http://{acme,globex,initech,newswire}.localtest.me:8090`) that you can change on demand. The first scheduler pass takes a baseline. After that:

```bash
make demo-mutate SCENARIO=acme-price-hike      # Acme raises Growth $79→$99; blog post + press release
make check-all                                 # mark all sources due; beat dispatches within ~60s
```

Within a few minutes (depending on your LLM speed) you'll see:
- **one** Critical/High event: the pricing page, the blog post and the press release are merged into a single event, and together they raise its confidence;
- evidence with a stance recorded per claim;
- an impact matrix and the Acme price history in the knowledge base;
- in-app toasts, plus six role-specific emails in Mailpit.

Other scenarios:
- `globex-partnership`: a partnership and a new product, which updates the relationship graph and the product catalogue.
- `initech-launch`: a product launch plus a new pricing add-on.
- `noise`: a cosmetic change, which should **not** alert.
- `reset`: restores the baseline sites.

`make brief` generates today's brief now; it also runs automatically at each organisation's configured hour.

## Local development

Run the infrastructure in Docker and the API/worker on the host:

```bash
docker compose up -d postgres redis objectstore searxng mailpit demo-sites
cd backend
cp ../.env.example .env   # then use localhost URLs (see below)
uv sync
uv run python -m app.cli migrate
uv run python -m app.cli seed-demo
uv run uvicorn app.main:app --reload
uv run celery -A app.workers.celery_app worker --pool=threads -Q pipeline,briefs,default   # and `beat`
uv run python -m app.cli run-all      # or run the whole pipeline inline, without Celery
cd ../frontend && npm install && npm run dev    # http://localhost:5173 (proxies /api to :8000)
```

Host-side `.env` values:
```
DATABASE_URL=postgresql+asyncpg://marketradar_app:marketradar_app@localhost:5433/marketradar
MIGRATION_DATABASE_URL=postgresql+asyncpg://marketradar:marketradar@localhost:5433/marketradar
OLLAMA_URL=http://localhost:11434
SEARXNG_URL=http://localhost:8888
S3_ENDPOINT=localhost:8333
SMTP_HOST=localhost
FRONTEND_URL=http://localhost:5173
```
Postgres is published on port **5433** so it doesn't collide with a local Postgres. On Windows, set `PLAYWRIGHT_ENABLED=false` for host runs, because headless Chromium needs the Proactor event loop while psycopg needs the Selector loop. The Linux worker image enables it.

### Tests

```bash
make test        # backend: 39 tests (unit + integration against real pgvector Postgres via testcontainers)
                 # frontend: vitest
make lint        # ruff, mypy, eslint, tsc
make api-client  # regenerate the typed frontend client after changing the API
```

The integration tests cover:
- the full agent pipeline, with the network mocked (respx);
- **row-level security enforcement**, using a non-superuser database role;
- idempotent replay and dedupe corroboration;
- the daily brief;
- the auth, RBAC and API-key flows.

## Operating notes

- **Tenancy.** Every domain table has `org_id` and a Postgres RLS policy. The app connects as a *non-owner* role, and each transaction sets `app.org_id`. Workers and login lookups use an explicit system bypass.
- **Reliability.**
  - Pipeline runs are idempotent: one key per source per schedule slot.
  - Runs are checkpointed. Retries resume from the last completed agent instead of starting over.
  - After Celery's retries are exhausted, a run is dead-lettered and can be **resumed** from the *Agent runs* page.
- **Models.** Set `LLM_MODEL_REASON` to a stronger model (e.g. `qwen2.5:7b-instruct`) for better impact analysis. Grounding and deterministic scoring keep 3B models usable. `LLM_PROVIDER=fake` runs everything on heuristics.
- **Source reliability.** Competitor-owned domains and SEC are tier 1. Major business press is tier 2. Unknown domains are tier 3. Social and UGC sites are tier 4. Override per organisation in *Settings → Organisation*.
- **Production** (`deploy/k8s`):
  - Provide Postgres with pgvector, Redis, S3, SMTP and Ollama. The migration role is separate from the app role.
  - Create `marketradar-secrets`, then run `kubectl apply -k deploy/k8s/overlays/prod`.
  - The migration Job runs `app.cli migrate`.
  - Keep `ALLOW_PRIVATE_SOURCES=false` and `ALLOW_SIGNUP=false`.

## Repository layout

```
backend/app/
  agents/        graph.py (LangGraph), nodes/ (one module per agent), scoring.py, runner.py, brief_graph.py
  monitoring/    fetchers (http, browser, feeds/EDGAR/GDELT/sitemaps), extract, normalize, pricing diff, search, politeness
  knowledge/     kb_service (pricing SCD-2, products, relationships, chunks), retrieval (pgvector + FTS, RRF)
  alerts/        routing, delivery (SSE + SMTP), Jinja templates for alerts, emails and briefs
  llm/           provider (Ollama / heuristic), schemas, prompts/*.j2, heuristic fallbacks
  api/v1/        REST + SSE endpoints        db/  models, RLS-aware sessions        workers/  Celery
frontend/src/    features/ (dashboard, events, competitors, sources, alerts, briefs, knowledge, runs, settings)
deploy/          k8s (kustomize), prometheus, grafana, searxng, seaweedfs, postgres init, demo-sites
scripts/demo_mutate.py   fictional competitor websites + change scenarios
```
