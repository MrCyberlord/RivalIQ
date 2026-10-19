import pytest

from app.intelligence_schemas import IntelligenceRequest
from app.services.intelligence import calculate_pricing
from app.services.recommendation_safety import evidence_quality, safe_recommendations
from test_intelligence import listing, analyze, pipeline


def evidence(count):
    rows = [listing(id=f"L{i + 1}").model_copy(update={"listed_price": 100 + i}) for i in range(max(1, count))]
    if not count:
        rows[0].product_name = "Unknown item"
    request = IntelligenceRequest(product_name="stainless steel bottle 500 ml", selling_price="799", cost="500")
    return rows, calculate_pricing(request, rows)


@pytest.mark.parametrize("count,band", [(0, "none"), (1, "single"), (2, "small"), (4, "small"), (5, "descriptive")])
def test_comparability_evidence_tiers_and_safe_guidance(count, band):
    rows, pricing = evidence(count)
    quality = evidence_quality(pricing)
    assert quality.band == band and quality.sample_size == count
    assert (pricing.median is not None) == (count >= 2)
    actions, safety = safe_recommendations([], rows, pricing)
    assert len(actions) == 3 and safety.replaced_count == 3
    assert "your" in actions[0].text.lower()
    assert all(set(a.source_ids).issubset({r.id for r in rows}) for a in actions)
    if not count:
        assert "unavailable" in actions[0].text
        assert not quality.source_ids
    if count == 1:
        assert "observation" in actions[0].text and "not a market benchmark" in actions[0].text
    if 2 <= count < 5:
        assert "small sample" in actions[0].text
    if count >= 5:
        assert "not statistically representative" in actions[0].text


@pytest.mark.parametrize("text,reason", [
    ("Reduce listing L1's price to INR 380.", "not_seller_directed"),
    ("Maintain L1 and L2 at INR 391 for your strategy.", "not_seller_directed"),
    ("For your strategy reduce the price of L1.", "not_seller_directed"),
    ("Set your price to INR 380.", "unsupported_price_target"),
    ("Set your price: INR 100.", "unsupported_price_target"),
    ("Reduce your price to INR 100.", "unsupported_price_target"),
    ("Your price should be INR 100.", "unsupported_price_target"),
    ("Review your INR 380 price against L1.", "unsupported_numerical_claim"),
    ("Your new offer guarantees profits.", "unsupported_outcome_claim"),
    ("Your product will sell more than L1.", "unsupported_outcome_claim"),
    ("Promote your product to boost sales.", "unsupported_outcome_claim"),
    ("Your product has a guaranteed competitive advantage.", "unsupported_outcome_claim"),
    ("Use your optimal price to maximise profit.", "unsupported_outcome_claim"),
])
def test_invalid_recommendations_replaced_not_repeated(text, reason):
    rows, pricing = evidence(2)
    actions, safety = safe_recommendations([{"text": text, "source_ids": ["L1", "L2"]}], rows, pricing)
    assert reason in safety.reason_codes
    assert text not in [a.text for a in actions]
    assert len(actions) == 3


@pytest.mark.parametrize("draft", [
    {"text": "Review your product.", "source_ids": ["L999"]},
    {"text": "Review your product with L999.", "source_ids": ["L1"]},
    {"text": "Review your product.", "source_ids": []},
    {"text": "Review your product."},
])
def test_missing_fabricated_and_uncited_inline_sources_use_real_fallback_evidence(draft):
    rows, pricing = evidence(2)
    actions, safety = safe_recommendations([draft], rows, pricing)
    assert "invalid_citation" in safety.reason_codes
    assert actions[0].source_ids == ["L1", "L2"]


def test_extra_recommendation_keys_are_replaced_without_validation_exception():
    rows, pricing = evidence(2)
    actions, safety = safe_recommendations([{"text": "Review your price.", "source_ids": ["L1"], "invented": True}], rows, pricing)
    assert "invalid_structure" in safety.reason_codes
    assert len(actions) == 3


def test_legitimate_seller_review_and_conditional_promotion_survive():
    rows, pricing = evidence(2)
    drafts = [
        {"text": "Review whether your INR 799 price is justified relative to comparable offers.", "source_ids": ["L1", "L2"]},
        {"text": "Consider testing a promotion for your product only after confirming equivalence and costs.", "source_ids": ["L1"]},
        {"text": "Clarify your product's stated material before changing its positioning.", "source_ids": ["L2"]},
    ]
    actions, safety = safe_recommendations(drafts, rows, pricing)
    assert [a.model_dump() for a in actions] == drafts
    assert safety.status == "passed"


def test_single_offer_caution_is_valid_seller_advice_and_not_a_positive_benchmark_claim():
    rows, pricing = evidence(1)
    drafts = [{"text": "Review your price using L1 as one observation, not a market benchmark.", "source_ids": ["L1"]}]
    actions, _ = safe_recommendations(drafts, rows, pricing)
    assert actions[0].text == drafts[0]["text"]


def test_broader_price_does_not_justify_seller_comparison():
    rows, pricing = evidence(0)
    actions, safety = safe_recommendations([{"text": "Review your overpriced product against L1.", "source_ids": ["L1"]}], rows, pricing)
    assert "insufficient_comparable_evidence" in safety.reason_codes
    assert "overpriced" not in actions[0].text


def test_zero_comparables_cannot_imply_a_comparable_price_comparison_exists():
    rows, pricing = evidence(0)
    actions, safety = safe_recommendations([{"text": "Review your price against comparable offers.", "source_ids": ["L1"]}], rows, pricing)
    assert "insufficient_comparable_evidence" in safety.reason_codes
    assert "unavailable" in actions[0].text


@pytest.mark.parametrize("change", ["competitor", "target", "unknown", "missing", "two"])
def test_pipeline_repairs_only_recommendations_without_extra_provider_calls(pipeline, change):
    drafts = pipeline[1]["report"]["recommendations"]
    if change == "competitor": drafts[0]["text"] = "Reduce listing L1's price to INR 380."
    if change == "target": drafts[0]["text"] = "Reduce your price to INR 380."
    if change == "unknown": drafts[0]["source_ids"] = ["L999"]
    if change == "missing": drafts[0].pop("source_ids")
    if change == "two": drafts.pop()
    response = analyze(pipeline)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["report"]["recommendations"]) == 3
    assert body["recommendation_safety"]["status"] == "adjusted"
    assert body["evidence_quality"]["band"] == "none"
    assert len(pipeline[2]) == 4


def test_other_narrative_citations_still_fail_closed(pipeline):
    pipeline[1]["report"]["market_overview"]["source_ids"] = ["L999"]
    assert analyze(pipeline).status_code == 502
