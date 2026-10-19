from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.intelligence_schemas import ProductAttributes
from app.schemas import SearchRequest


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attributes: ProductAttributes
    currency: Literal["INR", "USD", "GBP", "CAD", "AUD"] = "INR"
    market: str = "India"
    allow_cloud_processing: bool = Field(default=False, strict=True)

    @field_validator("market")
    @classmethod
    def market_supported(cls, value):
        return SearchRequest.supported_market(value.strip())


class Observation(BaseModel):
    id: str
    search_id: str
    source: str
    source_product_id: str | None = None
    product_url: str | None
    product_name: str | None
    merchant: str | None
    features: list[str] | None
    attributes: ProductAttributes
    listed_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None
    market: str
    retrieved_at: datetime


class PredictionSource(BaseModel):
    observation_id: str
    source_product_id: str | None
    product_url: str
    retrieved_at: datetime


class PredictionResponse(BaseModel):
    status: Literal["predicted", "insufficient_data", "unavailable"]
    reason: str
    experimental: bool = True
    predicted_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    currency: str
    model: str = "TabPFNRegressor (Prior Labs hosted default; tabpfn-client 0.6.1)"
    sample_count: int = Field(default=0, ge=0)
    minimum_samples: int = Field(default=30, ge=1)
    observation_start: datetime | None = None
    observation_end: datetime | None = None
    sources: list[PredictionSource] = Field(default_factory=list)
    limitations: list[str]

    @model_validator(mode="after")
    def prediction_requires_supported_metadata(self):
        if self.status == "predicted":
            if self.predicted_price is None or self.sample_count < self.minimum_samples or not self.observation_start or not self.observation_end:
                raise ValueError("Predictions require a price, sufficient samples and observation dates")
        elif self.predicted_price is not None:
            raise ValueError("Unavailable/insufficient responses cannot contain a predicted price")
        if self.observation_start and self.observation_end and self.observation_start > self.observation_end:
            raise ValueError("Observation date range is invalid")
        return self
