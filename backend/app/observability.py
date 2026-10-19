"""Opt-in Sentry with fixed spans and an outbound event allowlist."""
from contextlib import nullcontext
import logging
import os
import re

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

STAGES = {"serpapi.discovery", "gemma.discovery", "gemma.analysis", "mongodb.save", "mongodb.list", "mongodb.get"}
STAGES.update({"mongodb.observations.save", "mongodb.observations.read", "pricing.prepare", "pricing.tabpfn"})
ROUTES = {"/api/health", "/api/competitors/search", "/api/intelligence", "/api/reports", "/api/reports/{report_id}"}
ROUTES.add("/api/pricing/predict")
_guard = None


def scrub_event(event, hint):
    # Build a fresh event: deny unknown fields, even from SDK auto-enrichment.
    safe = {key: event[key] for key in ("event_id", "timestamp", "start_timestamp", "type", "level", "platform") if key in event}
    transaction = event.get("transaction", "")
    safe["transaction"] = next((route for route in ROUTES if transaction in (route, "GET " + route, "POST " + route)), "backend.request")
    trace = event.get("contexts", {}).get("trace", {})
    safe_trace = {key: value for key, value in trace.items() if key in {"trace_id", "span_id", "parent_span_id"}
                  and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{16,32}", value)}
    if trace.get("status") in {"ok", "internal_error", "unknown_error", "invalid_argument", "unavailable", "deadline_exceeded"}:
        safe_trace["status"] = trace["status"]
    if safe_trace:
        safe_trace["op"] = "http.server"
        safe["contexts"] = {"trace": safe_trace}
    if "exception" in event:
        values = []
        for error in event["exception"].get("values", []):
            frames = []
            for frame in error.get("stacktrace", {}).get("frames", []):
                cleaned = {key: frame[key] for key in ("lineno", "in_app") if key in frame}
                filename = str(frame.get("filename", "application.py")).replace("\\", "/").rsplit("/", 1)[-1]
                cleaned["filename"] = filename if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", filename) else "application.py"
                for key in ("function", "module"):
                    value = frame.get(key)
                    if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.<>]{0,120}", value):
                        cleaned[key] = value
                frames.append(cleaned)
            values.append({"type": error.get("type", "BackendError"), "value": "Backend exception; message omitted for privacy.",
                           "stacktrace": {"frames": frames}})
        safe["exception"] = {"values": values}
    if event.get("type") == "transaction":
        safe["spans"] = []
        for span in event.get("spans", []):
            if span.get("description") not in STAGES:
                continue
            item = {key: span[key] for key in ("trace_id", "span_id", "parent_span_id", "start_timestamp", "timestamp") if key in span}
            item.update(op="rivaliq.stage", description=span["description"])
            safe["spans"].append(item)
    return safe


def configure_sentry():
    global _guard
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn or _guard is not None:
        return _guard
    try:
        rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
        if not 0 <= rate <= 1:
            raise ValueError("Invalid rate")
        _guard = sentry_sdk.init(
            dsn=dsn, traces_sample_rate=rate, include_local_variables=False, include_source_context=False,
            data_collection={"user_info": False, "cookies": {"mode": "off"}, "http_headers": {"request": {"mode": "off"}},
                "http_bodies": [], "url_query_params": {"mode": "off"}, "gen_ai": {"inputs": False, "outputs": False},
                "graphql": {"document": False, "variables": False}, "database_query_data": False,
                "queues": False, "stack_frame_variables": False, "frame_context_lines": 0},
            max_request_body_size="never", default_integrations=False, auto_enabling_integrations=False,
            integrations=[StarletteIntegration(transaction_style="url"), FastApiIntegration(transaction_style="url")],
            before_send=scrub_event, before_send_transaction=scrub_event,
            before_breadcrumb=lambda breadcrumb, hint: None,
            enable_logs=False,
        )
    except (ValueError, TypeError):
        logging.getLogger("uvicorn.error").warning("Sentry configuration invalid; observability disabled.")
    return _guard


def stage(name: str):
    if name not in STAGES:
        raise ValueError("Unknown observability stage")
    return sentry_sdk.start_span(op="rivaliq.stage", name=name) if _guard is not None else nullcontext()


def capture_unexpected(error: Exception):
    if _guard is not None:
        sentry_sdk.capture_exception(error)


def flush_sentry():
    if _guard is not None:
        sentry_sdk.flush(timeout=2)
