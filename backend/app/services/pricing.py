import asyncio
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit

from app.observability import stage
from app.pricing_schemas import Observation, PredictionRequest, PredictionResponse, PredictionSource
from app.services.observations import LOOKBACK_DAYS, ObservationStore

MIN_PRODUCTS = 30
MIN_BRANDS = 3
MIN_TARGET_BRAND = 5
MAX_PRODUCTS = 200
FEATURES = ["brand", "category", "capacity_ml", "material", "observation_age_days", "source_engine"]
LIMITATIONS = [
    "Experimental observed-listing estimate, not a verified fair value, optimal selling price, demand forecast or profit-maximizing recommendation.",
    "Independent product identities are inferred from source product IDs or explicit brand/model; authenticity and product quality are unverified.",
    "Latest comparable observation per product within 90 days; repeated snapshots and retailer copies do not create independent examples.",
    "Same currency and market only; no conversion, confidence interval or demonstrated predictive accuracy is provided.",
    "Brand associations are observational, not proof of product value. Unobserved specifications, fees, shipping and retailer selection may bias results.",
    "Only structured public attributes, observation age/source engine and observed competitor prices are sent to Prior Labs; its data-processing/retention terms apply.",
]


def usable_target(request: PredictionRequest) -> bool:
    attrs = request.attributes
    return not attrs.conflicts and all(getattr(attrs, key) is not None for key in ("brand", "category", "capacity_ml", "material"))


def independent_samples(rows: list[Observation], request: PredictionRequest, cutoff: datetime) -> list[Observation]:
    eligible = []
    target = request.attributes
    for item in rows:
        attrs = item.attributes
        if (item.currency != request.currency or item.market != request.market or attrs.conflicts
                or not attrs.brand or not attrs.category or not attrs.material or attrs.capacity_ml is None
                or attrs.category.casefold() != target.category.casefold()
                or attrs.material.casefold() != target.material.casefold() or attrs.capacity_ml != target.capacity_ml
                or item.listed_price is None or not 0 < item.listed_price <= Decimal("1000000000000")
                or item.retrieved_at.tzinfo is None
                or not cutoff - timedelta(days=LOOKBACK_DAYS) <= item.retrieved_at <= cutoff
                or item.source != "serpapi_google_shopping" or not item.product_url):
            continue
        try:
            url = urlsplit(item.product_url)
            if url.scheme not in {"http", "https"} or not url.hostname:
                continue
        except ValueError:
            continue
        if not item.source_product_id and not attrs.model:
            continue  # URLs/retailers alone cannot establish product independence.
        eligible.append(item)

    # Union identities: a product ID can connect a model-labeled row to a later
    # row lacking that label. Do not count copies under different retailers.
    parent = list(range(len(eligible)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen = {}
    for index, item in enumerate(eligible):
        keys = []
        if item.source_product_id:
            keys.append(("provider_product", item.source, item.source_product_id))
        if item.attributes.model:
            keys.append(("brand_model", item.attributes.brand.casefold(), item.attributes.model.casefold()))
        for key in keys:
            if key in seen:
                parent[root(index)] = root(seen[key])
            seen[key] = index
    groups = {}
    for index, item in enumerate(eligible):
        group = root(index)
        prior = groups.get(group)
        if prior is None or (item.retrieved_at, item.id) > (prior.retrieved_at, prior.id):
            groups[group] = item
    return sorted(groups.values(), key=lambda item: (item.retrieved_at, item.id), reverse=True)[:MAX_PRODUCTS]


def build_features(samples: list[Observation], request: PredictionRequest, cutoff: datetime) -> dict:
    def row(attributes, age):
        return [attributes.brand.casefold(), attributes.category.casefold(), float(attributes.capacity_ml),
                attributes.material.casefold(), age, "google_shopping"]
    return {"columns": FEATURES, "train": [row(item.attributes, (cutoff - item.retrieved_at).total_seconds() / 86400) for item in samples],
            "target": [row(request.attributes, 0.0)], "prices": [float(item.listed_price) for item in samples]}


class HostedRegressor:
    """A killable isolated SDK worker: no blocked event loop, credential cache or late timeout threads."""
    def __init__(self):
        self.busy = False

    async def predict(self, table: dict, api_key: str, timeout: float) -> dict:
        if self.busy:
            return {"status": "unavailable", "code": "busy"}
        self.busy = True
        try:
            return await self._predict(table, api_key, timeout)
        finally:
            self.busy = False

    async def _predict(self, table: dict, api_key: str, timeout: float) -> dict:
        import sys
        worker_env = {key: value for key, value in os.environ.items() if not key.startswith("TABPFN") and key not in {
            "MONGODB_URI", "SENTRY_DSN", "SERPAPI_API_KEY"}}
        worker_env.update(TABPFN_API_KEY=api_key, TABPFN_CLIENT_TIMEOUT=str(timeout), TABPFN_CLIENT_UPLOAD_TIMEOUT=str(timeout),
                          TABPFN_CLIENT_ASYNC_POLL_TIMEOUT=str(timeout), TABPFN_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1")
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.services.tabpfn_worker",
            cwd=str(Path(__file__).resolve().parents[2]), env=worker_env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(table).encode()), timeout=timeout)
            if process.returncode != 0 or len(stdout) > 10000:
                return {"status": "unavailable", "code": "sdk_error"}
            result = json.loads(stdout)
            return result if isinstance(result, dict) else {"status": "unavailable", "code": "invalid_prediction"}
        except asyncio.TimeoutError:
            return {"status": "unavailable", "code": "timeout"}
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


REASONS = {
    "busy": "A hosted prediction is already running on this API worker. Try again after it completes.",
    "authentication": "Prior Labs authentication was rejected. Check TABPFN_API_KEY and account access.",
    "quota": "Prior Labs quota or rate limit reached. No prediction is available.",
    "timeout": "Hosted pricing prediction timed out. No fallback price was generated.",
    "network": "Prior Labs could not be reached. Existing intelligence remains available.",
    "sdk_missing": "Install backend/requirements-tabpfn.txt to enable the official hosted SDK.",
    "invalid_prediction": "Prior Labs did not return exactly one finite positive price.",
    "sdk_error": "The hosted SDK could not complete regression. Check account/model access and service availability.",
}


async def predict_pricing(request: PredictionRequest, store: ObservationStore, runner: HostedRegressor) -> PredictionResponse:
    base = dict(currency=request.currency, limitations=LIMITATIONS)
    if not usable_target(request):
        return PredictionResponse(status="insufficient_data", reason="Explicit brand, category, capacity and material without conflicts are required.", **base)
    cutoff = datetime.now(timezone.utc)
    try:
        with stage("pricing.prepare"):
            rows = await store.load(request, cutoff)
            samples = independent_samples(rows, request, cutoff)
    except Exception:
        return PredictionResponse(status="unavailable", reason="Historical observation storage is unavailable or exceeds the bounded read limit. MongoDB is required.", **base)
    base.update(sample_count=len(samples), observation_start=min((r.retrieved_at for r in samples), default=None),
                observation_end=max((r.retrieved_at for r in samples), default=None),
                sources=[PredictionSource(observation_id=r.id, source_product_id=r.source_product_id,
                                          product_url=r.product_url, retrieved_at=r.retrieved_at) for r in samples])
    brands = {r.attributes.brand.casefold() for r in samples}
    target_count = sum(r.attributes.brand.casefold() == request.attributes.brand.casefold() for r in samples)
    if len(samples) < MIN_PRODUCTS or len(brands) < MIN_BRANDS or target_count < MIN_TARGET_BRAND:
        return PredictionResponse(status="insufficient_data", reason=f"Need at least {MIN_PRODUCTS} independent comparable products across {MIN_BRANDS} brands, including {MIN_TARGET_BRAND} from the requested brand; found {len(samples)} products, {len(brands)} brands, {target_count} requested-brand products.", **base)
    if len({r.listed_price for r in samples}) < 2:
        return PredictionResponse(status="insufficient_data", reason="Observed target prices have no variation; meaningful regression is not supported.", **base)
    if not request.allow_cloud_processing:
        return PredictionResponse(status="unavailable", reason="Explicit consent to hosted processing is required; set allow_cloud_processing=true.", **base)
    key = os.getenv("TABPFN_API_KEY", "").strip()
    if not key:
        return PredictionResponse(status="unavailable", reason="Hosted pricing is not configured. Set TABPFN_API_KEY.", **base)
    try:
        timeout = float(os.getenv("TABPFN_TIMEOUT_SECONDS", "60"))
        if not 1 <= timeout <= 180:
            raise ValueError("Invalid timeout")
        with stage("pricing.tabpfn"):
            result = await runner.predict(build_features(samples, request, cutoff), key, timeout)
        if result.get("status") != "predicted":
            return PredictionResponse(status="unavailable", reason=REASONS.get(result.get("code"), REASONS["sdk_error"]), **base)
        value = result.get("value")
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1e12:
            return PredictionResponse(status="unavailable", reason=REASONS["invalid_prediction"], **base)
        rounded = float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        if rounded <= 0:
            return PredictionResponse(status="unavailable", reason=REASONS["invalid_prediction"], **base)
        return PredictionResponse(status="predicted", predicted_price=rounded, reason="Experimental estimate from independently observed comparable product prices.", **base)
    except Exception:
        logging.getLogger("uvicorn.error").warning("rivaliq_pricing outcome=unavailable")
        return PredictionResponse(status="unavailable", reason=REASONS["sdk_error"], **base)
