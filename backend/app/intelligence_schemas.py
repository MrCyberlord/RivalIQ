from decimal import Decimal
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import Competitor, SearchRequest

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
ShortText = Annotated[str, Field(min_length=1, max_length=600)]
SourceId = Annotated[str, Field(pattern=r"^L[1-9][0-9]*$")]


class ProductAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    capacity_ml: Decimal | None = Field(default=None, gt=0, le=10000000, allow_inf_nan=False)
    material: str | None = Field(default=None, min_length=1, max_length=80)
    brand: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    conflicts: list[str] = Field(default_factory=list, exclude=False)

    @field_validator("capacity_ml", mode="before")
    @classmethod
    def reject_boolean_capacity(cls, value):
        if isinstance(value, bool):
            raise ValueError("Capacity must be a volume in ml")
        return value


class IntelligenceRequest(SearchRequest):
    selling_price: Money = Field(gt=0)
    cost: Money | None = None
    max_results: int = Field(default=5, ge=1, le=6, strict=True)
    seller_attributes: ProductAttributes | None = None

    @field_validator("selling_price", "cost", mode="before")
    @classmethod
    def reject_boolean_prices(cls, value):
        if isinstance(value, bool):
            raise ValueError("Price must be a monetary amount")
        return value


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class DiscoveryPlan(ModelOutput):
    alternative_query: str = Field(min_length=2, max_length=160)


class Classification(ModelOutput):
    source_id: SourceId
    category: Literal["identical", "variant", "alternative", "uncertain"]
    reason: ShortText


class Finding(ModelOutput):
    text: ShortText
    source_ids: list[SourceId] = Field(min_length=1, max_length=12)


class NarrativeReport(ModelOutput):
    market_overview: Finding
    competitive_advantages: list[Finding] = Field(max_length=3)
    competitive_threats: list[Finding] = Field(max_length=3)
    pricing_observations: list[Finding] = Field(min_length=1, max_length=3)
    recommendations: list[Finding] = Field(min_length=3, max_length=3)


class GeneratedNarrativeReport(NarrativeReport):
    # Only recommendation drafts are recoverable. Malformed JSON, other findings,
    # upstream failures and incomplete envelopes still fail normally.
    recommendations: list[dict] = Field(default_factory=list, max_length=12)


class EvidenceQuality(BaseModel):
    sample_size: int
    band: Literal["none", "single", "small", "descriptive"]
    explanation: str
    source_ids: list[str]


class RecommendationSafety(BaseModel):
    policy_version: str = "seller-v1"
    status: Literal["passed", "adjusted"]
    replaced_count: int
    reason_codes: list[str]
    message: str


class IntelligenceReport(NarrativeReport):
    classifications: list[Classification] = Field(min_length=1, max_length=12)


def grounded_report_schema(source_ids: list[str], higher_priced: list[str], cheaper: list[str]) -> dict:
    """Constrain generation as well as validating the resulting citations afterwards."""
    schema = NarrativeReport.model_json_schema()
    schema["$defs"]["Finding"]["properties"]["source_ids"]["items"]["enum"] = source_ids
    for field, allowed in (("competitive_advantages", higher_priced), ("competitive_threats", cheaper)):
        prop = schema["properties"][field]
        prop["maxItems"] = min(2, len(allowed))
        if allowed:
            item = deepcopy(schema["$defs"]["Finding"])
            item["properties"]["source_ids"]["items"]["enum"] = allowed
            prop["items"] = item
    return schema


class Comparability(BaseModel):
    category: Literal["identical", "variant", "comparable_alternative", "alternative", "uncertain"]
    eligible: bool
    reason: str


class Listing(Competitor):
    id: str
    discovery_query: str
    duplicate_of: str | None = None
    source_product_id: str | None = None
    attributes: ProductAttributes = Field(default_factory=ProductAttributes)
    comparability: Comparability | None = None


class PriceComparison(BaseModel):
    source_id: str
    listed_price: Decimal
    seller_minus_listing: Decimal
    seller_difference_percent: Decimal | None


class PricingSummary(BaseModel):
    currency: str
    selling_price: Decimal
    cost: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    comparable_price_count: int
    minimum: Decimal | None
    median: Decimal | None
    maximum: Decimal | None
    comparisons: list[PriceComparison]
    benchmark_status: Literal["sufficient", "insufficient"] = "insufficient"
    benchmark_message: str = "Insufficient comparable products for a primary benchmark."
    minimum_required: int = 2


class MarketObservations(BaseModel):
    price_count: int
    minimum: Decimal | None
    median: Decimal | None
    maximum: Decimal | None
    source_ids: list[str]


class StageTiming(BaseModel):
    stage: str
    elapsed_ms: float
    outcome: str
    total_ms: float | None = None
    load_ms: float | None = None
    prompt_eval_ms: float | None = None
    generation_ms: float | None = None
    prompt_tokens: int | None = None
    generated_tokens: int | None = None
    tokens_per_second: float | None = None


class Performance(BaseModel):
    request_id: str
    total_ms: float
    stages: list[StageTiming]


class PersistenceStatus(BaseModel):
    status: Literal["saved", "disabled", "error"] = "disabled"
    report_id: str | None = None
    saved_at: str | None = None
    message: str = "Report saving is unavailable because MongoDB is not configured."
    elapsed_ms: float | None = None


class IntelligenceResponse(BaseModel):
    model: str
    market: str | None = None
    queries: list[str]
    listings: list[Listing]
    duplicate_count: int
    pricing: PricingSummary
    report: IntelligenceReport
    caveats: list[str]
    seller_attributes: ProductAttributes
    market_observations: MarketObservations
    performance: Performance | None = None
    persistence: PersistenceStatus = Field(default_factory=PersistenceStatus)
    evidence_quality: EvidenceQuality | None = None
    recommendation_safety: RecommendationSafety | None = None
