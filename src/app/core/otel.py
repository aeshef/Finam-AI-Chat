from __future__ import annotations

import os
from typing import Optional
from contextlib import contextmanager

try:  # Optional dependency
    from opentelemetry import trace  # type: ignore
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
    from opentelemetry.sdk.resources import Resource  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
except Exception:  # pragma: no cover
    trace = None  # type: ignore
    OTLPSpanExporter = None  # type: ignore
    Resource = None  # type: ignore
    TracerProvider = None  # type: ignore
    BatchSpanProcessor = None  # type: ignore


_initialized = False


def init_tracer(service_name: str = "finam-assistant") -> None:
    global _initialized
    if _initialized:
        return
    if trace is None or TracerProvider is None or OTLPSpanExporter is None or Resource is None or BatchSpanProcessor is None:
        # OpenTelemetry not installed; operate in no-op mode
        _initialized = True
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    resource = Resource(attributes={"service.name": service_name})
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint + "/v1/traces"))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer(name: str = "finam.orchestration"):
    if trace is None:
        class _NoopTracer:
            @staticmethod
            @contextmanager
            def start_as_current_span(_name: str):
                yield
        return _NoopTracer()
    return trace.get_tracer(name)


