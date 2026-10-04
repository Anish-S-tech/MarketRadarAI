# syntax=docker/dockerfile:1.7
# Targets: `api` (FastAPI, beat, migrations) and `worker` (Celery + headless Chromium for JS-rendered pages).
# Layer order keeps code changes cheap: dependencies and Chromium are cached below the application code.

FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
RUN useradd --system --uid 10001 --home /home/app --create-home app

FROM deps AS api
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

FROM deps AS worker
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PLAYWRIGHT_ENABLED=true
RUN playwright install --with-deps chromium && chmod -R o+rx /ms-playwright
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
USER app
EXPOSE 9100
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--pool=threads", "--concurrency=6", "-Q", "pipeline,briefs,default", "--loglevel=INFO"]
