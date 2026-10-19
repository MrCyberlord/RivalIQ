from decimal import Decimal, ROUND_HALF_UP, localcontext
from statistics import median
from time import perf_counter

import httpx
from fastapi import HTTPException

from app.config import OllamaSettings
from app.intelligence_schemas import (
    DiscoveryPlan, IntelligenceReport, IntelligenceRequest, IntelligenceResponse,
    Classification, Finding, Listing, MarketObservations, GeneratedNarrativeReport, PriceComparison, PricingSummary, grounded_report_schema,
)
from app.schemas import SearchRequest
from app.services.ollama import generate
from app.services.serpapi import search_competitors
from app.services.comparability import assess, extract_attributes, seller_attributes
from app.services.performance import Timings
from app.services.listing_identity import canonical_url, normalized
from app.services.recommendation_safety import evidence_quality, safe_recommendations


def identify_duplicates(listings: list[Listing]) -> list[Listing]:
    seen: dict[tuple, str] = {}
    for item in listings:
        # Different merchants, variants, and price observations remain separate.
        key = None
        attributes = (normalized(item.product_name), tuple(sorted(normalized(s) for s in item.features or [])))
        if item.product_url and item.merchant:
            key = ("url", canonical_url(item.product_url), normalized(item.merchant), item.listed_price, item.currency, attributes)
        elif item.product_name and item.merchant:
            key = ("title", normalized(item.product_name), normalized(item.merchant), item.listed_price, item.currency,
                   attributes)
        if key is not None:
            item.duplicate_of = seen.get(key)
            seen.setdefault(key, item.id)
    return listings


def rounded(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_pricing(request: IntelligenceRequest, listings: list[Listing]) -> PricingSummary:
    # External finite floats can have extreme exponents. Keep decimal arithmetic safe
    # without rounding source prices or silently dropping those observations.
    with localcontext() as context:
        context.prec = 700
        enrich_comparability(request, listings)
        return _calculate_pricing(request, listings)


def enrich_comparability(request: IntelligenceRequest, listings: list[Listing]):
    seller = seller_attributes(request.product_name, request.seller_attributes)
    for item in listings:
        item.attributes = extract_attributes(item.product_name, item.features, hints=seller)
        item.comparability = assess(seller, item.attributes)
    return seller


def _calculate_pricing(request: IntelligenceRequest, listings: list[Listing]) -> PricingSummary:
    comparisons = []
    for item in listings:
        if (item.duplicate_of or item.currency != request.currency or item.listed_price is None
                or not item.comparability or not item.comparability.eligible):
            continue
        amount = Decimal(str(item.listed_price))
        delta = request.selling_price - amount
        comparisons.append(PriceComparison(source_id=item.id, listed_price=amount,
            seller_minus_listing=rounded(delta),
            seller_difference_percent=rounded(delta / amount * 100) if amount else None))
    amounts = [item.listed_price for item in comparisons]
    profit = request.selling_price - request.cost if request.cost is not None else None
    return PricingSummary(currency=request.currency, selling_price=request.selling_price, cost=request.cost,
        gross_profit=rounded(profit) if profit is not None else None,
        gross_margin_percent=rounded(profit / request.selling_price * 100) if profit is not None else None,
        comparable_price_count=len(amounts), minimum=min(amounts) if len(amounts) >= 2 else None,
        median=rounded(median(amounts)) if len(amounts) >= 2 else None, maximum=max(amounts) if len(amounts) >= 2 else None,
        comparisons=comparisons, benchmark_status="sufficient" if len(amounts) >= 2 else "insufficient",
        benchmark_message=("Five or more comparable offers support descriptive comparisons, not statistical representativeness." if len(amounts) >= 5
            else "Two to four comparable offers support directional comparisons only; this is a small, unverified sample." if len(amounts) >= 2
            else "One comparable offer is an individual observation, not a market benchmark; at least two are required." if len(amounts) == 1
            else "Insufficient comparable products: reliable like-for-like pricing guidance is unavailable; at least two attribute-matched offers are required."))


def market_observations(request: IntelligenceRequest, listings: list[Listing]) -> MarketObservations:
    rows = [item for item in listings if not item.duplicate_of and item.currency == request.currency and item.listed_price is not None]
    amounts = [Decimal(str(item.listed_price)) for item in rows]
    with localcontext() as context:
        context.prec = 700
        return MarketObservations(price_count=len(amounts), minimum=min(amounts) if amounts else None,
            median=rounded(median(amounts)) if amounts else None, maximum=max(amounts) if amounts else None,
            source_ids=[item.id for item in rows])


def validate_references(report: IntelligenceReport, sources: set[str]) -> None:
    ids = [entry.source_id for entry in report.classifications]
    findings = [report.market_overview, *report.competitive_advantages, *report.competitive_threats,
                *report.pricing_observations, *report.recommendations]
    if set(ids) != sources or len(ids) != len(sources) or any(
        not set(f.source_ids).issubset(sources) for f in findings
    ):
        raise HTTPException(502, "Ollama returned invalid source references or incomplete classifications. No report was generated.")


async def analyze(request: IntelligenceRequest, api_key: str, client: httpx.AsyncClient,
                  settings: OllamaSettings, *, request_id: str | None = None, observations=None) -> IntelligenceResponse:
    timings = Timings(request_id)
    try:
        response = await _analyze(request, api_key, client, settings, timings, observations)
    except Exception:
        timings.finish("error")
        raise
    response.performance = timings.finish("ok")
    return response


async def _analyze(request: IntelligenceRequest, api_key: str, client: httpx.AsyncClient,
                   settings: OllamaSettings, timings: Timings, observations=None) -> IntelligenceResponse:
    if not api_key:
        raise HTTPException(503, "Competitor search is not configured. Set SERPAPI_API_KEY in backend/.env.")
    plan = await generate(DiscoveryPlan,
        "Create one short, broader shopping query for substitute products serving the same buyer need. "
        "Remove brand/model restrictions; do not merely add 'alternatives' to the original name. "
        "This is a search hypothesis, not evidence about the seller's product.",
        {"product_name": request.product_name}, client, settings, timings=timings)
    if normalized(plan.alternative_query) == normalized(request.product_name):
        raise HTTPException(502, "Ollama did not generate a distinct alternative discovery query. Try a more specific product name.")
    queries = [request.product_name, plan.alternative_query]
    listings = []
    for index, query in enumerate(queries):
        search = SearchRequest(product_name=query, market=request.market, currency=request.currency,
                               max_results=request.max_results)
        started = perf_counter()
        outcome = "error"
        try:
            results = await search_competitors(search, api_key, client, observations=observations, search_id=timings.request_id)
            outcome = "ok"
        finally:
            timings.record(f"serpapi_{index + 1}", started, outcome)
        for item in results:
            listings.append(Listing(**item.model_dump(), id=f"L{len(listings) + 1}", discovery_query=query,
                                    source_product_id=item._source_product_id))
    identify_duplicates(listings)
    unique = [item for item in listings if not item.duplicate_of]
    if not unique:
        raise HTTPException(404, "No shopping listings found for either query. No intelligence report was generated.")
    pricing = calculate_pricing(request, listings)
    seller = seller_attributes(request.product_name, request.seller_attributes)
    market = market_observations(request, listings)
    # Bound external text sent to the small local model; retain full data in the response.
    evidence = [{"id": item.id, "title": (item.product_name or "")[:140] or None,
                 "price": item.listed_price, "currency": item.currency,
                 "attributes": item.attributes.model_dump(mode="json", exclude_none=True),
                 "match": item.comparability.category, "primary_eligible": item.comparability.eligible}
                for item in unique]
    cheaper_than_seller = [c.source_id for c in pricing.comparisons if c.listed_price < request.selling_price]
    more_expensive = [c.source_id for c in pricing.comparisons if c.listed_price > request.selling_price]
    narrative = await generate(GeneratedNarrativeReport,
        "Analyze this shopping sample for this seller. Cite supplied IDs in every finding; at most 24 words per finding. "
        "Use stated seller attributes; never invent quality, demand or specifications. "
        "Advantages: only the seller's lower price versus higher_priced_comparable_ids; otherwise return []. "
        "A competitor's low price is a seller threat, never a seller advantage. Threats must cite cheaper_comparable_ids; otherwise []. "
        "Use at most two advantages and two threats. Recommendations: exactly three distinct, concrete actions tied to seller attributes, "
        "margin or evidence gaps; explicitly address 'your product' or 'your price'. Competitors are evidence, never products the seller controls. "
        "Never tell the seller to change, maintain or promote a competitor listing. Never invent price targets or promise demand, sales, profit or advantages. "
        "The lowest observed price is not automatically optimal. Suggest review or cautious tests after checking equivalence and costs, not numeric target prices. "
        "Cite the listings motivating each action. Acknowledge sample limits: zero=no guidance, one=individual observation, two to four=directional only, "
        "five or more=descriptive, not statistically representative. "
        "Use Python metrics; do no arithmetic or currency conversion. If primary status is insufficient, explicitly say so in pricing_observations. "
        "Broader prices describe market observations only, never a like-for-like benchmark or proof of seller competitiveness.",
        {"seller": {"name": request.product_name, "attributes": seller.model_dump(mode="json", exclude_none=True)},
         "listings": evidence, "primary_pricing": pricing.model_dump(mode="json", exclude={"comparisons"}),
         "broader_market": market.model_dump(mode="json"), "higher_priced_comparable_ids": more_expensive,
         "cheaper_comparable_ids": cheaper_than_seller}, client, settings, report=True, timings=timings,
         json_schema=grounded_report_schema([item.id for item in unique], more_expensive, cheaper_than_seller))
    if (any(not set(f.source_ids).issubset(more_expensive) for f in narrative.competitive_advantages)
            or any(not set(f.source_ids).issubset(cheaper_than_seller) for f in narrative.competitive_threats)):
        raise HTTPException(502, "Ollama returned unsupported competitive price claims. No report was generated.")
    recommendations, safety = safe_recommendations(narrative.recommendations, listings, pricing)
    report = IntelligenceReport(**{**narrative.model_dump(), "recommendations": recommendations}, classifications=[Classification(
        source_id=item.id, category="alternative" if item.comparability.category == "comparable_alternative" else item.comparability.category,
        reason=item.comparability.reason) for item in unique])
    if pricing.benchmark_status == "insufficient":
        report.pricing_observations = [Finding(text=pricing.benchmark_message, source_ids=[item.id for item in unique])]
    validate_references(report, {item.id for item in unique})
    return IntelligenceResponse(model=settings.model, market=request.market, queries=queries, listings=listings,
        duplicate_count=len(listings) - len(unique), pricing=pricing, report=report, seller_attributes=seller,
        market_observations=market, evidence_quality=evidence_quality(pricing), recommendation_safety=safety,
        caveats=["Attribute-rule classifications and AI conclusions are unverified estimates from a limited shopping sample.",
                 "Missing data is unknown. Seller specifications and listing authenticity have not been verified.",
                 "Primary aggregates require two attribute-matched offers. Broader market observations are not like-for-like benchmarks.",
                 "Duplicates are conservatively flagged, retained as evidence, and excluded from price aggregates.",
                 "Gross profit and margin use only the supplied cost; taxes, shipping and other fees are not included."])
