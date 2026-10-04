"""Provider-agnostic LLM access with schema-constrained JSON output.

`complete(task, schema, ctx)` renders `prompts/<task>.j2` with `ctx`, asks the model for JSON matching
`schema` (Ollama grammar-constrained `format`), validates with pydantic, retries with the validation
error fed back, and finally falls back to a deterministic heuristic so the pipeline never stalls.
"""

import asyncio
import contextvars
import json
import threading
import time
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

import ollama
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.core.logging import get_logger
from app.core.telemetry import LLM_FAILURES, LLM_LATENCY, LLM_TOKENS
from app.llm.heuristics import FALLBACKS

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)
Tier = Literal["classify", "reason"]

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "prompts"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Records which models/fallbacks served the current agent step (read by the tracing decorator).
llm_calls: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "llm_calls", default=None
)

SYSTEM_PROMPT = (
    "You are a meticulous competitive-intelligence analyst. Be factual and concise, never invent facts "
    "that are not in the provided material, and always answer with JSON that matches the requested schema."
)


def render_prompt(task: str, ctx: dict[str, Any]) -> str:
    return _env.get_template(f"{task}.j2").render(**ctx)


def _record(entry: dict[str, Any]) -> None:
    calls = llm_calls.get()
    if calls is not None:
        calls.append(entry)


class LLMProvider(Protocol):
    async def complete(self, task: str, schema: type[T], ctx: dict[str, Any], tier: Tier = "reason") -> T: ...

    async def embed(self, texts: list[str]) -> list[list[float]] | None: ...


class LLMUnavailable(Exception):
    pass


_llm_gate = threading.BoundedSemaphore(max(1, settings.llm_max_concurrency))

_TRANSIENT_MARKERS = ("out of memory", "cudamalloc", "timed out", "timeout", "server busy", "try again")


def _is_transient(e: Exception) -> bool:
    """Overload conditions worth waiting out (GPU OOM while another request holds VRAM, 5xx, timeouts);
    anything else (model missing, Ollama not running) falls back to heuristics immediately."""
    status = getattr(e, "status_code", None)
    msg = str(e).lower()
    return (isinstance(status, int) and status >= 500) or any(m in msg for m in _TRANSIENT_MARKERS)


class OllamaProvider:
    def __init__(self, host: str | None = None) -> None:
        self.host = host or settings.ollama_url
        self._clients: dict[int, ollama.AsyncClient] = {}
        self._embed_ok: bool | None = None

    @property
    def client(self) -> ollama.AsyncClient:
        # httpx async pools are bound to an event loop; workers run one loop per task.
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._clients:
            if len(self._clients) > 32:
                self._clients.clear()
            self._clients[loop_id] = ollama.AsyncClient(host=self.host, timeout=settings.llm_timeout_seconds)
        return self._clients[loop_id]

    def _model(self, tier: Tier) -> str:
        return settings.llm_model_classify if tier == "classify" else settings.llm_model_reason

    async def _chat(
        self, model: str, task: str, messages: list[dict[str, str]], schema: dict[str, Any] | Literal["json"]
    ) -> str:
        # Bound concurrent generations per process: each parallel request makes Ollama reserve another
        # KV cache, which exhausts small GPUs. Workers run one event loop per thread, so the gate is a
        # thread semaphore acquired off-loop.
        await asyncio.to_thread(_llm_gate.acquire)
        try:
            t0 = time.perf_counter()
            resp = await self.client.chat(
                model=model,
                messages=messages,
                format=schema,
                options={"temperature": settings.llm_temperature, "num_ctx": settings.llm_num_ctx},
                keep_alive="15m",
            )
        finally:
            _llm_gate.release()
        LLM_LATENCY.labels(model, task).observe(time.perf_counter() - t0)
        LLM_TOKENS.labels(model, "prompt").inc(resp.prompt_eval_count or 0)
        LLM_TOKENS.labels(model, "completion").inc(resp.eval_count or 0)
        return resp.message.content or ""

    async def complete(self, task: str, schema: type[T], ctx: dict[str, Any], tier: Tier = "reason") -> T:
        model = self._model(tier)
        prompt = render_prompt(task, ctx)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        json_schema = schema.model_json_schema()
        last_err: Exception | None = None
        attempts = settings.llm_max_retries + 1
        for attempt in range(attempts):
            # Small models occasionally return nothing under grammar-constrained decoding; the final attempt
            # falls back to plain JSON mode with the schema spelled out in the prompt.
            plain = attempt == attempts - 1 and attempt > 0
            fmt: dict[str, Any] | Literal["json"] = "json" if plain else json_schema
            if plain:
                schema_hint = (
                    f"Respond with JSON matching this JSON Schema:\n{json.dumps(json_schema)[:6000]}"
                )
                messages = [*messages[:1], {"role": "user", "content": f"{prompt}\n\n{schema_hint}"}]
            raw = ""
            try:
                raw = await self._chat(model, task, messages, fmt)
                result = schema.model_validate_json(raw)
                _record({"task": task, "model": model, "attempts": attempt + 1})
                return result
            except ValidationError as e:
                last_err = e
                LLM_FAILURES.labels(model, task).inc()
                if raw.strip():
                    messages = [
                        *messages[:2],
                        {"role": "assistant", "content": raw[:4000]},
                        {
                            "role": "user",
                            "content": f"That JSON was invalid: {str(e)[:800]}. Return corrected JSON only.",
                        },
                    ]
            except Exception as e:  # connection errors, model not found, timeouts, server overload
                last_err = e
                LLM_FAILURES.labels(model, task).inc()
                if not _is_transient(e) or attempt == attempts - 1:
                    break
                await asyncio.sleep(settings.llm_transient_backoff_seconds * (attempt + 1))
        log.warning("llm.fallback", task=task, model=model, error=str(last_err)[:300])
        return _fallback(task, schema, ctx, reason=str(last_err)[:200])

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts or self._embed_ok is False:
            return None
        try:
            resp = await self.client.embed(model=settings.embed_model, input=[t[:8000] for t in texts])
            vectors = [list(v) for v in resp.embeddings]
            if vectors and len(vectors[0]) != settings.embed_dim:
                log.error("llm.embed_dim_mismatch", got=len(vectors[0]), expected=settings.embed_dim)
                self._embed_ok = False
                return None
            self._embed_ok = True
            return vectors
        except Exception as e:
            log.warning("llm.embed_failed", error=str(e)[:200])
            return None


def _fallback(task: str, schema: type[T], ctx: dict[str, Any], reason: str) -> T:
    fn = FALLBACKS.get(task)
    if fn is None:
        raise LLMUnavailable(f"No fallback for task {task}: {reason}")
    result = fn(ctx)
    _record({"task": task, "model": "heuristic", "fallback_reason": reason})
    return schema.model_validate(result.model_dump())


class HeuristicProvider:
    """Offline provider (LLM_PROVIDER=fake): deterministic heuristics, no embeddings."""

    async def complete(self, task: str, schema: type[T], ctx: dict[str, Any], tier: Tier = "reason") -> T:
        render_prompt(task, ctx)  # still validate that templates render with the given context
        return _fallback(task, schema, ctx, reason="heuristic provider")

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = OllamaProvider() if settings.llm_provider == "ollama" else HeuristicProvider()
    return _provider


def set_llm(provider: LLMProvider | None) -> None:
    """Override the provider (tests)."""
    global _provider
    _provider = provider
