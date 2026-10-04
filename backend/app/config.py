from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "MarketRadarAI"
    log_level: str = "INFO"
    log_json: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://marketradar_app:marketradar_app@localhost:5433/marketradar"
    # Owner role used for migrations/DDL; the app role above is subject to row-level security.
    migration_database_url: str | None = None
    db_pool_size: int = 10

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Auth
    jwt_secret: str = "change-me-in-production-please-32b+"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    allow_signup: bool = True
    session_secret: str = "change-me-session-secret"
    oidc_enabled: bool = False
    oidc_name: str = "oidc"
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_discovery_url: str = ""
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )

    # Rate limiting
    rate_limit_default: str = "300/minute"
    rate_limit_auth: str = "10/minute"

    # LLM
    llm_provider: Literal["ollama", "fake"] = "ollama"
    # Not OLLAMA_HOST: that variable is the Ollama *server* bind address and is often set to 0.0.0.0.
    ollama_url: str = "http://localhost:11434"
    llm_model_classify: str = "llama3.2:latest"
    llm_model_reason: str = "llama3.2:latest"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 2
    llm_num_ctx: int = 4096  # prompts are truncated to fit; larger contexts cost VRAM per parallel request
    llm_max_concurrency: int = 2  # concurrent generations per worker process
    llm_transient_backoff_seconds: float = 10.0
    llm_temperature: float = 0.1

    # Monitoring
    user_agent: str = "MarketRadarBot/0.1 (+https://github.com/marketradar)"
    fetch_timeout_seconds: float = 30.0
    fetch_max_bytes: int = 5_000_000
    per_domain_min_interval_seconds: float = 5.0
    # Hosts that need slower pacing than the default (GDELT rate-limits well below its documented 1 req/5 s).
    per_domain_min_interval_overrides: dict[str, float] = Field(
        default_factory=lambda: {"api.gdeltproject.org": 15.0}
    )
    respect_robots: bool = True
    allow_private_sources: bool = False
    playwright_enabled: bool = True
    min_text_chars_before_browser: int = 400
    default_significance_threshold: float = 0.45
    scheduler_jitter_seconds: int = 60

    # Research
    searxng_url: str | None = "http://localhost:8888"
    research_max_results: int = 6
    research_max_claims: int = 3
    sec_user_agent: str = "MarketRadarAI admin@example.com"

    # Object storage
    s3_endpoint: str = "localhost:8333"
    s3_access_key: str = "marketradar"
    s3_secret_key: str = "marketradar-secret"
    s3_bucket: str = "snapshots"
    s3_secure: bool = False
    s3_enabled: bool = True

    # Email
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    smtp_from: str = "MarketRadar <alerts@marketradar.local>"
    email_enabled: bool = True
    email_immediate_min_priority: Literal["low", "medium", "high", "critical"] = "high"
    email_max_per_user_per_hour: int = 10
    alert_dedupe_hours: int = 24

    # Observability
    otel_exporter_otlp_endpoint: str | None = None
    worker_metrics_port: int = 9100

    # LangGraph
    use_postgres_checkpointer: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """psycopg-style URL (used by LangGraph checkpointer)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
