import json
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app import observability


def test_no_dsn_does_not_initialize_or_start_spans(monkeypatch):
    initialize, start, capture, flush = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(observability, "_guard", None)
    monkeypatch.setattr(sentry_sdk, "init", initialize)
    monkeypatch.setattr(sentry_sdk, "start_span", start)
    monkeypatch.setattr(sentry_sdk, "capture_exception", capture)
    monkeypatch.setattr(sentry_sdk, "flush", flush)
    assert observability.configure_sentry() is None
    with observability.stage("mongodb.save"):
        pass
    observability.capture_unexpected(RuntimeError("private"))
    observability.flush_sentry()
    initialize.assert_not_called()
    start.assert_not_called()
    capture.assert_not_called()
    flush.assert_not_called()


@pytest.mark.parametrize("rate", ["-1", "1.5", "nan", "not-a-rate"])
def test_bad_sentry_config_is_nonfatal(monkeypatch, rate):
    monkeypatch.setattr(observability, "_guard", None)
    monkeypatch.setenv("SENTRY_DSN", "https://secret@example.invalid/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", rate)
    initialize = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", initialize)
    assert observability.configure_sentry() is None
    initialize.assert_not_called()


def test_scrubber_drops_request_customer_data_locals_breadcrumbs_and_span_data():
    event = {"event_id": "a" * 32, "transaction": "/api/reports/secret-customer-id", "user": {"email": "private"},
        "request": {"data": "product descriptions", "headers": {"Authorization": "secret"}}, "extra": {"api_key": "secret"},
        "breadcrumbs": {"values": [{"message": "secret"}]}, "message": "secret", "type": "transaction",
        "contexts": {"customer": {"details": "secret"}, "trace": {"trace_id": "b" * 32, "span_id": "c" * 16, "data": {"secret": 1}}},
        "exception": {"values": [{"type": "RuntimeError", "value": "secret-uri", "stacktrace": {"frames": [
            {"filename": "app.py", "function": "search", "lineno": 20, "vars": {"api_key": "secret"}, "context_line": "private code"}]}}]},
        "spans": [{"description": "mongodb.save", "data": {"query": "secret"}, "span_id": "d" * 16},
                  {"description": "https://serpapi.com?api_key=secret"}]}
    result = observability.scrub_event(event, {})
    serialized = json.dumps(result)
    assert all(text not in serialized for text in ("secret", "private", "product descriptions", "context_line", "Authorization"))
    assert result["transaction"] == "backend.request"
    assert len(result["spans"]) == 1
    assert result["exception"]["values"][0]["stacktrace"]["frames"][0]["lineno"] == 20


def test_real_sdk_captures_scrubbed_exception_and_stage_transaction_in_memory(monkeypatch):
    captured = []

    class MemoryTransport(Transport):
        def capture_envelope(self, envelope):
            captured.append(envelope)

    original_init = sentry_sdk.init
    monkeypatch.setattr(observability, "_guard", None)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "1")
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: original_init(transport=MemoryTransport, **options))
    try:
        assert observability.configure_sentry() is not None
        test_app = FastAPI()

        @test_app.post("/api/intelligence")
        async def fail(body: dict):
            with observability.stage("serpapi.discovery"):
                raise RuntimeError("customer-secret API key and full product description")

        with TestClient(test_app, raise_server_exceptions=False) as client:
            response = client.post("/api/intelligence?api_key=customer-secret", headers={"Authorization": "customer-secret"},
                                   json={"product_name": "customer-secret full product description", "cost": 500})
            assert response.status_code == 500
        with sentry_sdk.start_transaction(name="/api/intelligence", op="http.server"):
            for name in observability.STAGES:
                with observability.stage(name):
                    pass
        sentry_sdk.flush()
        events = [item.payload.json for envelope in captured for item in envelope.items if item.type in {"event", "transaction"}]
        assert any("exception" in event for event in events)
        assert any(any(span.get("description") == "serpapi.discovery" for span in event.get("spans", [])) for event in events)
        assert {span["description"] for event in events for span in event.get("spans", [])} == observability.STAGES
        assert "customer-secret" not in json.dumps(events)
        assert "full product description" not in json.dumps(events)
        assert all("request" not in event and "user" not in event and "breadcrumbs" not in event for event in events)
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)
