from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

MARKETS = {"India": "in", "United States": "us", "United Kingdom": "uk", "Canada": "ca", "Australia": "au"}


class SearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    product_name: str = Field(min_length=1, max_length=200)
    market: str = "India"
    currency: Literal["INR", "USD", "GBP", "CAD", "AUD"] = "INR"
    max_results: int = Field(default=5, ge=1, le=20, strict=True)

    @field_validator("market")
    @classmethod
    def supported_market(cls, value: str) -> str:
        for name in MARKETS:
            if name.casefold() == value.casefold():
                return name
        raise ValueError(f"Supported markets: {', '.join(MARKETS)}")


class Competitor(BaseModel):
    # Internal provider metadata, preserving the existing public search contract.
    _source_product_id: str | None = PrivateAttr(default=None)
    product_name: str | None
    listed_price: float | None
    currency: str | None
    merchant: str | None
    product_url: str | None
    source: str = "serpapi_google_shopping"
    retrieved_at: datetime
    features: list[str] | None = None


class SearchResponse(BaseModel):
    competitors: list[Competitor]
