from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from app.intelligence_schemas import IntelligenceRequest, IntelligenceResponse


class ReportSummary(BaseModel):
    id: str
    created_at: datetime
    product_name: str
    currency: str
    selling_price: str
    listing_count: int
    comparable_price_count: int
    benchmark_status: Literal["sufficient", "insufficient"]
    model: str
    analysis_ms: float | None


class ReportList(BaseModel):
    reports: list[ReportSummary]
    next_offset: int | None


class SavedReport(BaseModel):
    id: str
    created_at: datetime
    schema_version: int = 1
    seller_inputs: IntelligenceRequest
    intelligence: IntelligenceResponse

    @model_validator(mode="after")
    def retain_original_market(self):
        # Earlier snapshots omitted market in the intelligence object; the saved
        # seller request is the original observed context, not an inferred country.
        self.intelligence.market = self.seller_inputs.market
        # Old snapshots can predate seller-safety checks. Produce a safe read view
        # without a provider call or rewriting the historical database document.
        from app.services.recommendation_safety import safe_recommendations, evidence_quality
        report = self.intelligence
        recommendations, safety = safe_recommendations(
            [r.model_dump() for r in report.report.recommendations], report.listings, report.pricing)
        if recommendations != report.report.recommendations or report.recommendation_safety is None:
            report.recommendation_safety = safety
        report.report.recommendations = recommendations
        report.evidence_quality = evidence_quality(report.pricing)
        return self
