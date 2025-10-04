from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.adapters.finam_client import FinamAPIClient
from src.app.core.cache import SimpleTTLCache
from src.app.core.rate_limit import TokenBucket
from src.mcp.runtime import MCPRuntime
from src.app.core.metrics import record_latency, record_cache, record_retry, record_rl_wait, record_error


@dataclass
class ToolRequest:
    method: str
    path: str


class ToolRouter:
    """Generic executor for Finam API requests via FinamAPIClient.

    No hardcoded cases; simply proxies METHOD+PATH and optional kwargs.
    """

    def __init__(self, client: FinamAPIClient, cache: Optional[SimpleTTLCache] = None, backend: str = "http") -> None:
        self.client = client
        self.cache = cache or SimpleTTLCache()
        # Defaults: 5 rps burst 10; can be env-configured later
        self.bucket = TokenBucket(rate_per_sec=5.0, burst=10)
        self.backend = backend
        self.mcp = MCPRuntime()

    def execute(self, request: ToolRequest, **kwargs: Any) -> Dict[str, Any]:
        params = kwargs.get("params") if kwargs else None
        # Rate limit
        wait_sec = self.bucket.consume(1.0)
        if wait_sec > 0:
            import time as _t

            _t.sleep(wait_sec)
        record_rl_wait(wait_sec)

        # Cache GET requests only
        if request.method.upper() == "GET":
            hit, value = self.cache.get(request.method, request.path, params)
            if hit:
                record_cache(True, request.method, request.path)
                return value
            record_cache(False, request.method, request.path)
            # backoff retries / or MCP
            with record_latency(request.method, request.path, self.backend):
                resp = self._execute_backend(request.method, request.path, **kwargs)
            # Cache basic endpoints with low volatility
            ttl = 30 if "/orderbook" in request.path or "/quotes" in request.path else 300
            self.cache.set(request.method, request.path, params, resp, ttl_seconds=ttl)
            return resp
        with record_latency(request.method, request.path, self.backend):
            return self._execute_backend(request.method, request.path, **kwargs)

    def _execute_backend(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        if self.backend == "mcp":
            return self.mcp.call_raw(method, path, **kwargs)
        return self._with_backoff(method, path, **kwargs)

    def _with_backoff(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        import time as _t

        delays = [0.1, 0.3, 0.7, 1.5]
        last_resp: Optional[Dict[str, Any]] = None
        for i, d in enumerate(delays):
            resp = self.client.execute_request(method, path, **kwargs)
            # Treat HTTP errors in response by convention: {'error': ..., 'status_code': ...}
            if not (isinstance(resp, dict) and "error" in resp and resp.get("status_code") in (429, 500, 502, 503, 504)):
                return resp
            last_resp = resp
            record_retry(method, path)
            _t.sleep(d)
        if isinstance(last_resp, dict) and "status_code" in last_resp:
            record_error(method, path, str(last_resp.get("status_code")))
        return last_resp or {}


