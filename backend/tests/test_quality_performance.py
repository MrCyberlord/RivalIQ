import logging
from decimal import Decimal
from time import perf_counter

import pytest

from app.intelligence_schemas import IntelligenceRequest, ProductAttributes, grounded_report_schema
from app.services.comparability import assess, extract_attributes, seller_attributes
from app.services.intelligence import calculate_pricing, market_observations
from app.services.performance import Timings
from test_intelligence import analyze, listing, pipeline  # shared mocked HTTP providers


@pytest.mark.parametrize("capacity", ["500 ml", "0.5L", "0.5 litre", "0.5 ltr", "500 milliliters"])
def test_explicit_unit_normalization(capacity):
    value = extract_attributes(f"Milton stainless steel bottle {capacity}")
    assert value.capacity_ml == Decimal(500)
    assert value.brand == "milton" and value.material == "stainless steel" and value.category == "bottle"


def test_unknown_brand_and_specs_are_not_inferred():
    value = extract_attributes("Amazing premium container")
    assert value.brand is None
    assert value.capacity_ml is None and value.material is None


@pytest.mark.parametrize("text", ["plastic-free bottle 500ml", "non-plastic bottle 500ml", "bottle 500ml not made of plastic"])
def test_negated_material_is_unknown_not_a_positive_specification(text):
    assert extract_attributes(text).material is None


def test_accessory_is_not_a_full_product_benchmark():
    seller = extract_attributes("Milton stainless steel bottle 500ml")
    source = extract_attributes("Milton stainless steel bottle cap for 500ml")
    assert not assess(seller, source).eligible


@pytest.mark.parametrize("name", ["steel bottle 500-750ml", "bottle 500ml 1L", "stainless steel plastic bottle 500ml",
    "2 x 500ml stainless steel bottle", "pack of 10 stainless steel bottles 500ml"])
def test_ambiguous_or_multipack_not_eligible(name):
    seller = extract_attributes("stainless steel bottle 500ml")
    match = assess(seller, extract_attributes(name))
    assert not match.eligible and match.category == "uncertain"


@pytest.mark.parametrize("name,category,eligible", [
    ("Milton stainless steel bottle 500ml", "variant", True),
    ("Cello stainless steel bottle 500ml", "comparable_alternative", True),
    ("Milton stainless steel bottle 750ml", "variant", False),
    ("Cello plastic bottle 500ml", "alternative", False),
    ("Cello stainless steel flask 500ml", "alternative", False),
    ("Bottle 500ml", "uncertain", False),
    ("Unspecified product", "uncertain", False),
])
def test_comparability_rules(name, category, eligible):
    seller = extract_attributes("Milton stainless steel bottle 500ml")
    match = assess(seller, extract_attributes(name))
    assert match.category == category and match.eligible is eligible


def test_identical_requires_explicit_brand_model_and_no_conflict():
    seller = extract_attributes("Milton model: XYZ bottle 500ml")
    assert assess(seller, extract_attributes("Milton model: XYZ bottle 500ml")).category == "identical"
    assert not assess(seller, extract_attributes("Milton model: XYZ bottle 750ml")).eligible
    assert not assess(seller, extract_attributes("Milton model: ABC bottle 500ml")).eligible


def test_seller_conflicts_not_silently_overridden():
    seller = seller_attributes("Milton stainless steel bottle 500ml", ProductAttributes(capacity_ml=750))
    assert "capacity_ml" in seller.conflicts
    assert not assess(seller, extract_attributes("Milton stainless steel bottle 750ml")).eligible


def test_unknown_seller_has_no_primary_benchmark():
    request = IntelligenceRequest(product_name="bottle", selling_price=100)
    rows = [listing(), listing("L2")]
    primary = calculate_pricing(request, rows)
    assert primary.comparable_price_count == 0 and primary.median is None
    assert primary.benchmark_status == "insufficient"
    assert market_observations(request, rows).price_count == 2


def test_cheap_different_material_and_size_cannot_skew_primary_benchmark():
    request = IntelligenceRequest(product_name="Milton stainless steel bottle 500ml", selling_price=150)
    rows = [listing().model_copy(update={"product_name": "Milton stainless steel bottle 500ml", "listed_price": 200}),
            listing("L2").model_copy(update={"product_name": "Cello stainless steel bottle 0.5L", "listed_price": 240}),
            listing("L3").model_copy(update={"product_name": "Cello plastic bottle 500ml", "listed_price": 10}),
            listing("L4").model_copy(update={"product_name": "Milton stainless steel bottle 250ml", "listed_price": 20})]
    primary = calculate_pricing(request, rows)
    assert primary.comparable_price_count == 2 and primary.median == Decimal("220.00")
    assert [c.source_id for c in primary.comparisons] == ["L1", "L2"]
    market = market_observations(request, rows)
    assert market.price_count == 4 and market.median == Decimal("110.00")


def test_one_comparable_offer_does_not_create_market_benchmark():
    request = IntelligenceRequest(product_name="stainless steel bottle 500ml", selling_price=150)
    primary = calculate_pricing(request, [listing()])
    assert primary.comparable_price_count == 1
    assert primary.minimum is None and primary.median is None and primary.maximum is None
    assert len(primary.comparisons) == 1  # a factual listing comparison is still available


def setup_quality(pipeline):
    config = pipeline[1]
    config["first_rows"] = [{"title": "Acme stainless steel bottle 500ml", "extracted_price": 100, "price": "INR 100"},
                            {"title": "Cello stainless steel bottle 500ml", "extracted_price": 200, "price": "INR 200"}]
    config["second_rows"] = [{"title": "Cello plastic bottle 500ml", "extracted_price": 10, "price": "INR 10"}]
    return {"seller_attributes": {"brand": "Acme", "material": "stainless steel"}}


def test_live_shape_preserves_contract_and_derives_classifications(pipeline):
    response = analyze(pipeline, **setup_quality(pipeline))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pricing"]["median"] == "150.00"
    assert body["market_observations"]["median"] == "100.00"
    assert [r["comparability"]["category"] for r in body["listings"]] == ["variant", "comparable_alternative", "alternative"]
    assert len(body["report"]["classifications"]) == 3


@pytest.mark.parametrize("source", ["L1", "L3"])
def test_competitor_low_price_never_seller_advantage(pipeline, source):
    inputs = setup_quality(pipeline)
    pipeline[1]["report"]["competitive_advantages"] = [{"text": "Low pricing is a seller advantage.", "source_ids": [source]}]
    assert analyze(pipeline, **inputs).status_code == 502


def test_supported_price_advantage_and_threat(pipeline):
    inputs = setup_quality(pipeline)
    pipeline[1]["report"]["competitive_advantages"] = [{"text": "Your listed price is lower than this comparable offer.", "source_ids": ["L2"]}]
    pipeline[1]["report"]["competitive_threats"] = [{"text": "This comparable listing is priced below your offer.", "source_ids": ["L1"]}]
    assert analyze(pipeline, **inputs).status_code == 200


def test_no_comparable_products_explicit_even_if_model_omits_warning(pipeline):
    pipeline[1]["report"]["pricing_observations"] = [{"text": "The broad median proves your product is overpriced.", "source_ids": ["L1"]}]
    body = analyze(pipeline).json()
    assert body["pricing"]["benchmark_status"] == "insufficient"
    assert "Insufficient comparable products" in body["report"]["pricing_observations"][0]["text"]
    assert all("overpriced" not in f["text"] for f in body["report"]["pricing_observations"])


def test_ollama_timing_conversion_and_safe_logs(pipeline, caplog):
    pipeline[1]["metadata"] = {"total_duration": 3_000_000_000, "load_duration": 100_000_000,
        "prompt_eval_duration": 500_000_000, "eval_duration": 2_000_000_000,
        "prompt_eval_count": 400, "eval_count": 100, "secret_field": "do not log"}
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        body = analyze(pipeline).json()
    stages = body["performance"]["stages"]
    assert [s["stage"] for s in stages] == ["ollama_discovery", "serpapi_1", "serpapi_2", "ollama_report"]
    assert stages[-1]["load_ms"] == 100 and stages[-1]["prompt_eval_ms"] == 500
    assert stages[-1]["generation_ms"] == 2000 and stages[-1]["tokens_per_second"] == 50
    assert body["performance"]["total_ms"] >= sum(s["elapsed_ms"] for s in stages) - 0.01
    assert "rivaliq_request" in caplog.text
    assert all(secret not in caplog.text for secret in ("test-key", "Acme", "do not log", "serpapi.com", "Ignore all instructions"))


def test_missing_or_malformed_timing_metadata_stays_unknown():
    timings = Timings()
    timings.record("ollama_report", perf_counter(), "error", {"eval_duration": -1, "load_duration": "123", "eval_count": True})
    assert timings.stages[0].generation_ms is None
    assert timings.stages[0].load_ms is None and timings.stages[0].generated_tokens is None
    assert timings.stages[0].tokens_per_second is None


def test_generation_schema_cannot_cite_cheaper_competitor_as_advantage():
    schema = grounded_report_schema(["L1", "L2", "L3"], ["L2"], ["L1"])
    assert schema["properties"]["competitive_advantages"]["items"]["properties"]["source_ids"]["items"]["enum"] == ["L2"]
    assert schema["properties"]["competitive_threats"]["items"]["properties"]["source_ids"]["items"]["enum"] == ["L1"]
    empty = grounded_report_schema(["L1"], [], [])
    assert empty["properties"]["competitive_advantages"]["maxItems"] == 0
    assert empty["properties"]["competitive_threats"]["maxItems"] == 0


def test_http_timing_and_pipeline_share_request_id(pipeline):
    response = analyze(pipeline)
    assert response.headers["server-timing"].startswith("app;dur=")
    assert response.headers["x-rivaliq-request-id"] == response.json()["performance"]["request_id"]


def test_failure_still_logs_request_and_stage_without_sensitive_content(pipeline, caplog):
    pipeline[1]["serp_status"] = 500
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        assert analyze(pipeline).status_code == 502
    assert "outcome=error" in caplog.text and '"stage":"serpapi_1"' in caplog.text
    assert "test-key" not in caplog.text
