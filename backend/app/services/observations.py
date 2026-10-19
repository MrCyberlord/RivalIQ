import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo import UpdateOne

from app.observability import stage
from app.pricing_schemas import Observation, PredictionRequest
from app.schemas import Competitor
from app.services.comparability import extract_attributes
from app.services.listing_identity import canonical_url, normalized
from app.services.reports import sanitize_document

LOOKBACK_DAYS = 90
MAX_OBSERVATIONS = 2000


def observation_documents(rows: list[Competitor], market: str, search_id: str, secrets=()) -> list[dict]:
    documents = {}
    for item in rows:
        raw = sanitize_document(item.model_dump(mode="json"), secrets)
        attributes = extract_attributes(raw["product_name"], raw["features"])
        pid = item._source_product_id
        if sanitize_document(pid, secrets) != pid:
            pid = None
        identity = (item.source, pid, canonical_url(raw["product_url"]) if raw["product_url"] else None,
                    normalized(raw["merchant"]), normalized(raw["product_name"]), raw["listed_price"], raw["currency"],
                    attributes.model_dump(mode="json"))
        oid = hashlib.sha256(json.dumps([search_id, identity], sort_keys=True).encode()).hexdigest()
        if oid in documents:
            continue
        observation = Observation(id=oid, search_id=search_id, source=item.source, source_product_id=pid,
            product_url=raw["product_url"], product_name=raw["product_name"], merchant=raw["merchant"], features=raw["features"],
            attributes=attributes, listed_price=raw["listed_price"], currency=raw["currency"], market=market,
            retrieved_at=item.retrieved_at)
        document = observation.model_dump(mode="json", exclude={"id"})
        document.update(_id=oid, schema_version=1, retrieved_at=item.retrieved_at, captured_at=datetime.now(timezone.utc),
                        capacity_ml_value=float(attributes.capacity_ml) if attributes.capacity_ml is not None else None)
        documents[oid] = document
    return list(documents.values())


class ObservationStore:
    def __init__(self, collection=None, *, secrets=()):
        self.collection = collection
        self.secrets = secrets

    async def capture(self, rows: list[Competitor], market: str, search_id: str | None = None):
        if self.collection is None or not rows:
            return
        try:
            documents = observation_documents(rows, market, search_id or uuid4().hex, self.secrets)
            with stage("mongodb.observations.save"):
                await self.collection.bulk_write([UpdateOne({"_id": doc["_id"]}, {"$setOnInsert": doc,
                    "$addToSet": {"retrieval_timestamps": doc["retrieved_at"]}}, upsert=True) for doc in documents], ordered=False)
        except Exception:
            # Discovery remains usable even when observation storage fails. Never log payload/error text.
            logging.getLogger("uvicorn.error").warning("rivaliq_observations outcome=error; discovery preserved")

    async def load(self, request: PredictionRequest, cutoff: datetime) -> list[Observation]:
        if self.collection is None:
            raise RuntimeError("Observation storage unavailable")
        with stage("mongodb.observations.read"):
            cursor = self.collection.find({"currency": request.currency, "market": request.market,
                "attributes.category": request.attributes.category.casefold() if request.attributes.category else None,
                "attributes.material": request.attributes.material.casefold() if request.attributes.material else None,
                "capacity_ml_value": float(request.attributes.capacity_ml) if request.attributes.capacity_ml else None,
                "retrieved_at": {"$gte": cutoff - timedelta(days=LOOKBACK_DAYS), "$lte": cutoff}}).sort("retrieved_at", -1).limit(MAX_OBSERVATIONS + 1)
            documents = await cursor.to_list(length=MAX_OBSERVATIONS + 1)
        if len(documents) > MAX_OBSERVATIONS:
            raise RuntimeError("Observation window exceeds bounded read limit")
        return [Observation.model_validate({**doc, "id": str(doc["_id"])}) for doc in documents]
