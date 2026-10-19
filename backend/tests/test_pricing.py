import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import get_observation_store, get_pricing_runner
from app.intelligence_schemas import ProductAttributes
from app.pricing_schemas import Observation, PredictionRequest
from app.services.observations import ObservationStore, observation_documents
from app.services.pricing import HostedRegressor, build_features, independent_samples
from test_intelligence import analyze, pipeline

NOW = datetime.now(timezone.utc)
TARGET = {"brand": "milton", "category": "bottle", "capacity_ml": "1000", "material": "stainless steel"}


def observed(index=0, **changes):
    values = dict(id=f"o{index}", search_id=f"search{index}", source="serpapi_google_shopping", source_product_id=f"p{index}",
        product_url=f"https://shop.test/product/{index}", product_name=f"Observed product {index}", merchant=f"Retailer {index}",
        features=None, attributes=ProductAttributes(**{**TARGET, "brand": ["milton", "cello", "borosil"][index % 3], "model": f"model{index}"}),
        listed_price=100 + index, currency="INR", market="India", retrieved_at=NOW - timedelta(hours=index + 1))
    values.update(changes)
    return Observation(**values)


@pytest.fixture
def pricing(pipeline, monkeypatch):
    store = SimpleNamespace(load=AsyncMock(return_value=[observed(i) for i in range(30)]), capture=AsyncMock())
    runner = SimpleNamespace(predict=AsyncMock(return_value={"status": "predicted", "value": 123.456}))
    pipeline[0].app.dependency_overrides[get_observation_store] = lambda: store
    pipeline[0].app.dependency_overrides[get_pricing_runner] = lambda: runner
    monkeypatch.setenv("TABPFN_API_KEY", "test-tabpfn-key")
    return store, runner


def predict(pipeline, **changes):
    return pipeline[0].post("/api/pricing/predict", json={"attributes": TARGET, "currency": "INR", "market": "India", "allow_cloud_processing": True, **changes})


def test_real_observations_gate_and_prediction_metadata(pipeline, pricing):
    response = predict(pipeline)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "predicted" and body["predicted_price"] == 123.46
    assert body["sample_count"] == 30 and body["minimum_samples"] == 30
    assert body["experimental"] is True and body["observation_start"] and body["observation_end"]
    assert len(body["sources"]) == 30 and "confidence_interval" not in body
    assert "TabPFNRegressor" in body["model"]
    assert len(pipeline[2]) == 0  # prediction never reruns discovery or Gemma


def test_repeated_snapshots_and_price_changes_not_independent():
    request = PredictionRequest(attributes=TARGET)
    rows = [observed(0), observed(0, id="unchanged", search_id="later-search", retrieved_at=NOW),
            observed(0, id="changed-price", listed_price=200, retrieved_at=NOW - timedelta(minutes=1))]
    samples = independent_samples(rows, request, NOW)
    assert len(samples) == 1 and samples[0].id == "unchanged"


def test_retailer_copies_and_identity_aliases_union():
    base = observed()
    other_pid = base.model_copy(update={"id": "alias", "source_product_id": "another-id", "merchant": "different merchant"})
    no_model = other_pid.model_copy(update={"id": "no-model", "attributes": other_pid.attributes.model_copy(update={"model": None})})
    assert len(independent_samples([base, other_pid, no_model], PredictionRequest(attributes=TARGET), NOW)) == 1


@pytest.mark.parametrize("updates", [
    {"currency": "USD"}, {"currency": None}, {"market": "United States"}, {"listed_price": 0}, {"listed_price": None},
    {"retrieved_at": NOW + timedelta(days=1)}, {"retrieved_at": NOW - timedelta(days=91)},
    {"retrieved_at": NOW.replace(tzinfo=None)}, {"source": "invented"}, {"product_url": None},
    {"product_url": "javascript:alert(1)"}, {"attributes": ProductAttributes(**{**TARGET, "capacity_ml": 500})},
    {"attributes": ProductAttributes(**{**TARGET, "material": "plastic"})},
    {"attributes": ProductAttributes(**{**TARGET, "category": "flask"})},
    {"attributes": ProductAttributes(**{**TARGET, "brand": None})},
    {"attributes": ProductAttributes(**{**TARGET, "conflicts": ["multipack"]})},
    {"source_product_id": None, "attributes": ProductAttributes(**TARGET)},
])
def test_only_genuine_usable_comparable_source_rows(updates):
    assert independent_samples([observed(**updates)], PredictionRequest(attributes=TARGET), NOW) == []


def test_model_identity_without_provider_id_can_be_independent():
    assert len(independent_samples([observed(source_product_id=None)], PredictionRequest(attributes=TARGET), NOW)) == 1


def test_features_exclude_target_leakage_retailer_ids_and_text():
    table = build_features([observed()], PredictionRequest(attributes=TARGET), NOW)
    assert table["columns"] == ["brand", "category", "capacity_ml", "material", "observation_age_days", "source_engine"]
    assert table["prices"] == [100]
    features = json.dumps({key: table[key] for key in ("columns", "train", "target")})
    assert all(text not in features for text in ("listed_price", "selling_price", "cost", "Retailer", "Observed product", "shop.test", "model0", "p0"))
    assert table["train"][0][4] > 0 and table["target"][0][4] == 0


@pytest.mark.parametrize("failure", ["too_few", "one_brand", "unseen_brand", "no_variation"])
def test_insufficient_data_never_calls_hosted_api(pipeline, pricing, failure):
    store, runner = pricing
    if failure == "too_few": store.load.return_value = [observed(i) for i in range(29)]
    if failure == "one_brand":
        store.load.return_value = [observed(i, attributes=ProductAttributes(**{**TARGET, "model": f"m{i}"})) for i in range(30)]
    if failure == "unseen_brand":
        store.load.return_value = [observed(i, attributes=ProductAttributes(**{**TARGET, "brand": f"other{i % 3}", "model": f"m{i}"})) for i in range(30)]
    if failure == "no_variation": store.load.return_value = [observed(i, listed_price=100) for i in range(30)]
    assert predict(pipeline).json()["status"] == "insufficient_data"
    runner.predict.assert_not_called()


def test_missing_required_attributes_and_conflicts_refuse_without_database(pipeline, pricing):
    for attributes in ({"category": "bottle"}, {**TARGET, "conflicts": ["material"]}):
        assert predict(pipeline, attributes=attributes).json()["status"] == "insufficient_data"
    pricing[0].load.assert_not_called()
    pricing[1].predict.assert_not_called()


def test_missing_key_and_no_consent_are_explicit_unavailable(pipeline, pricing, monkeypatch):
    assert predict(pipeline, allow_cloud_processing=False).json()["status"] == "unavailable"
    monkeypatch.setenv("TABPFN_API_KEY", "")
    assert "TABPFN_API_KEY" in predict(pipeline).json()["reason"]
    pricing[1].predict.assert_not_called()


def test_database_failure_does_not_break_intelligence(pipeline, pricing):
    pricing[0].load.side_effect = RuntimeError("private connection URI")
    response = predict(pipeline)
    assert response.json()["status"] == "unavailable" and "private" not in response.text
    assert analyze(pipeline).status_code == 200


@pytest.mark.parametrize("value", [None, "123", True, -1, 0, float("nan"), float("inf"), 0.001, 1e13])
def test_invalid_prediction_is_never_presented_as_a_price(pipeline, pricing, value):
    pricing[1].predict.return_value = {"status": "predicted", "value": value}
    body = predict(pipeline).json()
    assert body["status"] == "unavailable" and body["predicted_price"] is None


@pytest.mark.parametrize("code", ["authentication", "quota", "network", "timeout", "sdk_missing", "sdk_error", "busy"])
def test_safe_hosted_failure_statuses(pipeline, pricing, code):
    pricing[1].predict.return_value = {"status": "unavailable", "code": code}
    body = predict(pipeline).json()
    assert body["status"] == "unavailable" and body["predicted_price"] is None
    assert "test-tabpfn-key" not in str(body)
    assert pipeline[0].get("/api/health").status_code == 200


def test_unexpected_hosted_error_never_leaks_text(pipeline, pricing):
    pricing[1].predict.side_effect = RuntimeError("test-tabpfn-key private payload")
    response = predict(pipeline)
    assert response.json()["status"] == "unavailable"
    assert "test-tabpfn-key" not in response.text and "private payload" not in response.text


@pytest.mark.parametrize("extra", [{"selling_price": 100}, {"api_key": "not-allowed"}, {"currency": "XXX"}, {"market": "unknown"}, {"allow_cloud_processing": "yes"}])
def test_prediction_contract_rejects_credentials_target_prices_invalid_context(pipeline, pricing, extra):
    assert predict(pipeline, **extra).status_code == 422
    pricing[1].predict.assert_not_called()


def test_observation_capture_dedup_preserves_real_timestamps_and_history():
    from app.schemas import Competitor
    base = Competitor(product_name="Milton stainless steel bottle 1L model: S1", listed_price=123.45, currency="INR",
        merchant="shop", product_url="https://shop.test/item?utm_source=one", retrieved_at=NOW, features=["1L"])
    base._source_product_id = "real-provider-id"
    duplicate = base.model_copy(update={"product_url": "https://shop.test/item?utm_source=two"})
    docs = observation_documents([base, duplicate], "India", "search-a")
    assert len(docs) == 1 and docs[0]["retrieved_at"] == NOW
    assert docs[0]["source_product_id"] == "real-provider-id" and docs[0]["attributes"]["capacity_ml"] == "1000"
    assert docs[0]["currency"] == "INR" and docs[0]["listed_price"] == "123.45"
    assert observation_documents([base], "India", "search-b")[0]["_id"] != docs[0]["_id"]
    changed = base.model_copy(update={"listed_price": 150})
    assert len(observation_documents([base, changed], "India", "search-a")) == 2


def test_discovery_persists_even_when_later_gemma_fails(pipeline):
    collection = SimpleNamespace(bulk_write=AsyncMock())
    store = ObservationStore(collection)
    pipeline[0].app.dependency_overrides[get_observation_store] = lambda: store
    pipeline[1]["report"] = "invalid JSON"
    assert analyze(pipeline).status_code == 502
    assert collection.bulk_write.await_count == 2
    batches = [call.args[0] for call in collection.bulk_write.call_args_list]
    assert batches[0][0]._filter == batches[1][-1]._filter  # unchanged copy across two queries, one search ID


def test_observation_database_failure_preserves_search_contract(pipeline):
    collection = SimpleNamespace(bulk_write=AsyncMock(side_effect=RuntimeError("private URI")))
    pipeline[0].app.dependency_overrides[get_observation_store] = lambda: ObservationStore(collection)
    response = pipeline[0].post("/api/competitors/search", json={"product_name": "bottle"})
    assert response.status_code == 200
    assert set(response.json()) == {"competitors"}
    assert all("source_product_id" not in row for row in response.json()["competitors"])


def test_source_identifiers_kept_internal_in_search_but_retained_for_observations(pipeline):
    pipeline[1]["first_rows"][0]["product_id"] = "google-product-id"
    store = SimpleNamespace(capture=AsyncMock())
    pipeline[0].app.dependency_overrides[get_observation_store] = lambda: store
    response = analyze(pipeline)
    assert response.status_code == 200
    assert store.capture.call_args_list[0].args[0][0]._source_product_id == "google-product-id"
    assert response.json()["listings"][0]["source_product_id"] == "google-product-id"


def test_killable_worker_timeout_and_credential_isolation(monkeypatch):
    process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=asyncio.TimeoutError), kill=MagicMock(), wait=AsyncMock())
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setenv("MONGODB_URI", "private-mongo-uri")
    monkeypatch.setenv("SENTRY_DSN", "private-dsn")
    monkeypatch.setenv("TABPFN_CLIENT_API_URL", "https://untrusted.invalid")
    runner = HostedRegressor()
    result = asyncio.run(runner.predict({"train": []}, "private-key", 1))
    assert result["code"] == "timeout"
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
    env = create.call_args.kwargs["env"]
    assert env["TABPFN_API_KEY"] == "private-key" and env["TABPFN_DISABLE_TELEMETRY"] == "1"
    assert all(key not in env for key in ("MONGODB_URI", "SENTRY_DSN", "SERPAPI_API_KEY", "TABPFN_CLIENT_API_URL"))
    assert "private-key" not in str(create.call_args.args)
    assert runner.busy is False


def test_busy_worker_does_not_queue_or_spawn():
    runner = HostedRegressor()
    runner.busy = True
    assert asyncio.run(runner.predict({}, "key", 1))["code"] == "busy"


def test_observation_reads_are_bounded_and_currency_market_filtered():
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    collection = SimpleNamespace(find=MagicMock(return_value=cursor))
    store = ObservationStore(collection)
    assert asyncio.run(store.load(PredictionRequest(attributes=TARGET), NOW)) == []
    query = collection.find.call_args.args[0]
    assert query["currency"] == "INR" and query["market"] == "India"
    assert query["capacity_ml_value"] == 1000.0 and query["retrieved_at"]["$lte"] == NOW
    cursor.limit.assert_called_once_with(2001)
    cursor.to_list.return_value = [{}] * 2001
    with pytest.raises(RuntimeError):
        asyncio.run(store.load(PredictionRequest(attributes=TARGET), NOW))


def test_observation_storage_scrubs_credentials():
    from app.schemas import Competitor
    row = Competitor(product_name="Milton bottle 1L", listed_price=10, currency="INR", merchant="shop",
                     product_url="https://user:pass@shop.test/p?api_key=private-key", features=["private-key"], retrieved_at=NOW)
    row._source_product_id = "private-key"
    document = observation_documents([row], "India", "search", secrets=("private-key",))[0]
    assert "private-key" not in str(document) and "user:pass" not in str(document)
    assert document["source_product_id"] is None


def test_response_schema_cannot_claim_prediction_without_sufficient_evidence():
    from pydantic import ValidationError
    from app.pricing_schemas import PredictionResponse
    with pytest.raises(ValidationError):
        PredictionResponse(status="predicted", reason="invalid", currency="INR", limitations=[], predicted_price=100)
    with pytest.raises(ValidationError):
        PredictionResponse(status="insufficient_data", reason="invalid", currency="INR", limitations=[], predicted_price=100)
