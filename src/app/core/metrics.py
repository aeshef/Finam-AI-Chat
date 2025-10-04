from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict

from prometheus_client import Counter, Histogram, Gauge

HTTP_LATENCY = Histogram(
    "finam_http_latency_seconds",
    "Latency of HTTP/MCP calls",
    labelnames=("method", "path", "backend"),
)
HTTP_ERRORS = Counter(
    "finam_http_errors_total",
    "HTTP errors",
    labelnames=("method", "path", "status"),
)
CACHE_HITS = Counter("finam_cache_hits_total", "Cache hits", labelnames=("method", "path"))
CACHE_MISSES = Counter("finam_cache_misses_total", "Cache misses", labelnames=("method", "path"))
RETRIES = Counter("finam_retries_total", "Retries executed", labelnames=("method", "path"))
RL_WAIT_SECONDS = Histogram("finam_ratelimit_wait_seconds", "Rate limit wait")

LLM_TOKENS = Counter("finam_llm_tokens_total", "LLM tokens", labelnames=("kind",))
LLM_COST_USD = Counter("finam_llm_cost_usd_total", "LLM cost in USD")


@contextmanager
def record_latency(method: str, path: str, backend: str):
    start = time.time()
    try:
        yield
    finally:
        HTTP_LATENCY.labels(method=method, path=path, backend=backend).observe(time.time() - start)


def record_error(method: str, path: str, status: str) -> None:
    HTTP_ERRORS.labels(method=method, path=path, status=status).inc()


def record_cache(hit: bool, method: str, path: str) -> None:
    if hit:
        CACHE_HITS.labels(method=method, path=path).inc()
    else:
        CACHE_MISSES.labels(method=method, path=path).inc()


def record_retry(method: str, path: str) -> None:
    RETRIES.labels(method=method, path=path).inc()


def record_rl_wait(seconds: float) -> None:
    RL_WAIT_SECONDS.observe(max(0.0, seconds))


def record_llm_usage(prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
    if prompt_tokens:
        LLM_TOKENS.labels(kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS.labels(kind="completion").inc(completion_tokens)
    if cost_usd:
        LLM_COST_USD.inc(cost_usd)
