import json
from unittest.mock import AsyncMock, MagicMock

from bson import BSON, ObjectId
from pymongo.errors import AutoReconnect, OperationFailure, ServerSelectionTimeoutError
import pytest

from app.main import get_report_store
from app.main import app
from fastapi.testclient import TestClient
from app.services.reports import ReportStore, create_report_store, sanitize_document
from test_intelligence import analyze, pipeline


@pytest.fixture
def database(pipeline):
    collection = MagicMock()
    collection.insert_one = AsyncMock()
    collection.find_one = AsyncMock()
    cursor = collection.find.return_value
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    store = ReportStore(collection, configured=True, secrets=("test-key",))
    pipeline[0].app.dependency_overrides[get_report_store] = lambda: store
    return collection, store


def test_completed_report_save_and_reopen_without_provider_calls(pipeline, database):
    collection, store = database
    response = analyze(pipeline)
    assert response.status_code == 200
    body = response.json()
    assert body["persistence"]["status"] == "saved"
    document = collection.insert_one.call_args.args[0]
    assert BSON.encode(document)  # valid BSON, including decimal-string precision
    assert document["seller_inputs"]["selling_price"] == "120"
    assert document["seller_inputs"]["cost"] == "80"
    for field in ("listings", "report", "pricing", "performance", "queries"):
        assert document["intelligence"][field] == body[field]
    assert document["schema_version"] == 1 and document["created_at"].tzinfo is not None
    assert document["intelligence"]["persistence"]["status"] == "saved"
    collection.find_one.return_value = document
    calls = len(pipeline[2])
    reopened = pipeline[0].get(f"/api/reports/{body['persistence']['report_id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["intelligence"]["report"] == body["report"]
    assert reopened.json()["seller_inputs"]["product_name"] == "Acme Bottle 500 ml"
    assert len(pipeline[2]) == calls
    collection.find_one.assert_awaited_once_with({"_id": document["_id"]})


def test_unsafe_legacy_recommendations_reopen_with_safe_view_without_rerunning(pipeline, database):
    import copy
    response = analyze(pipeline)
    document = copy.deepcopy(database[0].insert_one.call_args.args[0])
    intelligence = document["intelligence"]
    intelligence.pop("recommendation_safety", None)
    intelligence.pop("evidence_quality", None)
    intelligence["report"]["recommendations"][0]["text"] = "Reduce listing L1's price to INR 380."
    database[0].find_one.return_value = document
    before = len(pipeline[2])
    reopened = pipeline[0].get(f"/api/reports/{response.json()['persistence']['report_id']}")
    assert reopened.status_code == 200
    body = reopened.json()["intelligence"]
    assert "Reduce listing" not in body["report"]["recommendations"][0]["text"]
    assert body["recommendation_safety"]["status"] == "adjusted"
    assert body["evidence_quality"]["band"] == "none"
    assert len(pipeline[2]) == before
    assert "Reduce listing" in document["intelligence"]["report"]["recommendations"][0]["text"]


def test_lightweight_history_projection_and_pagination(pipeline, database):
    collection, _ = database
    analyze(pipeline)
    document = collection.insert_one.call_args.args[0]
    collection.find.return_value.to_list.return_value = [document, document]
    response = pipeline[0].get("/api/reports?limit=1&offset=0")
    assert response.status_code == 200
    assert response.json()["next_offset"] == 1
    assert len(response.json()["reports"]) == 1
    assert "intelligence" not in response.text and "recommendations" not in response.text
    collection.find.assert_called_once_with({}, {"summary": 1})
    collection.find.return_value.sort.assert_called_once_with("_id", -1)
    collection.find.return_value.limit.assert_called_once_with(2)


def test_empty_history(pipeline, database):
    assert pipeline[0].get("/api/reports").json() == {"reports": [], "next_offset": None}


@pytest.mark.parametrize("report_id", ["bad", "a" * 23, "z" * 24, '{"$ne":null}', "a" * 25])
def test_invalid_ids_rejected_before_database_access(pipeline, database, report_id):
    response = pipeline[0].get(f"/api/reports/{report_id}")
    assert response.status_code == 422
    database[0].find_one.assert_not_called()


def test_valid_missing_report_404(pipeline, database):
    database[0].find_one.return_value = None
    assert pipeline[0].get(f"/api/reports/{ObjectId()}").status_code == 404


@pytest.mark.parametrize("operation", ["save", "list", "get"])
@pytest.mark.parametrize("failure", [AutoReconnect("secret-uri"), OperationFailure("secret credentials"), ServerSelectionTimeoutError("secret-host")])
def test_database_failures_are_safe_and_preserve_analysis(pipeline, database, operation, failure):
    collection, _ = database
    if operation == "save":
        collection.insert_one.side_effect = failure
        response = analyze(pipeline)
        assert response.status_code == 200
        assert response.json()["persistence"]["status"] == "error"
        assert len(response.json()["report"]["recommendations"]) == 3
    elif operation == "list":
        collection.find.return_value.to_list.side_effect = failure
        response = pipeline[0].get("/api/reports")
        assert response.status_code == 503
    else:
        collection.find_one.side_effect = failure
        response = pipeline[0].get(f"/api/reports/{ObjectId()}")
        assert response.status_code == 503
    assert "secret" not in response.text


def test_missing_configuration_preserves_workflow_and_explains_history(pipeline):
    body = analyze(pipeline).json()
    assert body["persistence"]["status"] == "disabled"
    assert "not configured" in body["persistence"]["message"]
    assert pipeline[0].get("/api/reports").status_code == 503
    assert pipeline[0].get(f"/api/reports/{ObjectId()}").status_code == 503
    assert pipeline[0].get("/api/reports/invalid").status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "offset=-1", "offset=10001"])
def test_history_bounds(pipeline, database, query):
    assert pipeline[0].get(f"/api/reports?{query}").status_code == 422
    database[0].find.assert_not_called()


def test_corrupt_stored_report_returns_safe_error(pipeline, database):
    database[0].find_one.return_value = {"_id": ObjectId()}
    assert pipeline[0].get(f"/api/reports/{ObjectId()}").status_code == 503


def test_secrets_not_saved_even_if_present_in_source_url_or_text(pipeline, database):
    pipeline[1]["first_rows"][0]["product_link"] = "https://user:password@shop.test/item?api_key=test-key&size=500#details"
    pipeline[1]["first_rows"][0]["extensions"] = ["test-key mongodb+srv://user:password@cluster.test/db"]
    response = analyze(pipeline)
    assert response.status_code == 200
    document = database[0].insert_one.call_args.args[0]
    serialized = json.dumps(document, default=str)
    assert "test-key" not in serialized and "user:password" not in serialized
    assert document["intelligence"]["listings"][0]["product_url"] == "https://shop.test/item?size=500#details"


def test_disabled_store_does_not_create_driver(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("app.services.reports.AsyncMongoClient", factory)
    assert create_report_store().configured is False
    factory.assert_not_called()


def test_invalid_config_does_not_break_startup_or_leak_uri(monkeypatch, caplog):
    monkeypatch.setenv("MONGODB_URI", "bad://user:secret@host")
    store = create_report_store()
    assert store.configured and store.collection is None
    assert "secret" not in caplog.text


def test_driver_is_async_configured_with_bounded_timeout(monkeypatch):
    factory = MagicMock()
    monkeypatch.setenv("MONGODB_URI", "mongodb://user:secret@localhost:27017")
    monkeypatch.setattr("app.services.reports.AsyncMongoClient", factory)
    store = create_report_store()
    assert store.client is factory.return_value
    assert factory.call_args.kwargs["timeoutMS"] == 5000
    assert factory.call_args.kwargs["tz_aware"] is True


def test_sanitizer_excludes_credential_fields():
    assert sanitize_document({"api_key": "never-store", "report": ["public"]}, ()) == {"report": ["public"]}


def test_database_client_closed_by_application_lifespan(monkeypatch):
    client = MagicMock()
    client.close = AsyncMock()
    store = ReportStore(client=client)
    monkeypatch.setattr("app.main.create_report_store", lambda: store)
    with TestClient(app) as http:
        assert http.get("/api/health").status_code == 200
    client.close.assert_awaited_once()


def test_unexpected_save_exception_preserves_result_and_is_captured(pipeline, database, monkeypatch):
    captured = MagicMock()
    monkeypatch.setattr("app.services.reports.capture_unexpected", captured)
    database[0].insert_one.side_effect = RuntimeError("private customer info")
    response = analyze(pipeline)
    assert response.status_code == 200
    assert response.json()["persistence"]["status"] == "error"
    assert "private customer" not in response.text
    captured.assert_called_once()
