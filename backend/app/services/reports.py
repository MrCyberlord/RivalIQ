import logging
import os
import re
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError
from pymongo import AsyncMongoClient, DESCENDING
from pymongo.errors import PyMongoError

from app.intelligence_schemas import IntelligenceRequest, IntelligenceResponse, PersistenceStatus
from app.observability import capture_unexpected, stage
from app.report_schemas import ReportList, ReportSummary, SavedReport

PRIVATE_PARAMS = {"api_key", "apikey", "key", "token", "access_token", "password", "secret", "signature", "auth", "authorization"}


def sanitize_document(value, secrets):
    """Store typed application data only, with URL credentials and known secrets removed."""
    if isinstance(value, dict):
        return {key: sanitize_document(item, secrets) for key, item in value.items() if key.casefold() not in PRIVATE_PARAMS}
    if isinstance(value, list):
        return [sanitize_document(item, secrets) for item in value]
    if not isinstance(value, str):
        return value
    if value.startswith(("http://", "https://")):
        try:
            parts = urlsplit(value)
            host = parts.netloc.rsplit("@", 1)[-1]
            query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.casefold() not in PRIVATE_PARAMS]
            fragment = "" if any(key + "=" in parts.fragment.casefold() for key in PRIVATE_PARAMS) else parts.fragment
            value = urlunsplit((parts.scheme, host, parts.path, urlencode(query), fragment))
        except ValueError:
            value = "[redacted URL]"
    value = re.sub(r"mongodb(?:\+srv)?://[^\s]+", "[redacted database URI]", value)
    for secret in sorted(set(filter(None, secrets)), key=len, reverse=True):
        value = value.replace(secret, "[redacted]")
    return value


class ReportStore:
    def __init__(self, collection=None, *, client=None, configured=False, secrets=(), observation_collection=None):
        self.collection = collection
        self.client = client
        self.configured = configured
        self.secrets = secrets
        self.observation_collection = observation_collection

    def require_collection(self):
        if self.collection is None:
            message = "Report history is unavailable because MongoDB is not configured." if not self.configured else "Report history is temporarily unavailable. Check MongoDB configuration."
            raise HTTPException(503, message)
        return self.collection

    async def save(self, inputs: IntelligenceRequest, result: IntelligenceResponse) -> PersistenceStatus:
        if not self.configured:
            return PersistenceStatus()
        started = perf_counter()
        outcome = "error"
        try:
            collection = self.require_collection()
            oid, now = ObjectId(), datetime.now(timezone.utc)
            summary = ReportSummary(id=str(oid), created_at=now, product_name=inputs.product_name,
                currency=inputs.currency, selling_price=str(inputs.selling_price), listing_count=len(result.listings),
                comparable_price_count=result.pricing.comparable_price_count, benchmark_status=result.pricing.benchmark_status,
                model=result.model, analysis_ms=result.performance.total_ms if result.performance else None)
            payload = sanitize_document({"seller_inputs": inputs.model_dump(mode="json"),
                "intelligence": result.model_dump(mode="json"), "summary": summary.model_dump(mode="json")}, self.secrets)
            saved_status = PersistenceStatus(status="saved", report_id=str(oid), saved_at=now.isoformat(), message="Report saved.")
            payload["intelligence"]["persistence"] = saved_status.model_dump(mode="json")
            document = {"_id": oid, "created_at": now, "schema_version": 1, **payload}
            with stage("mongodb.save"):
                await collection.insert_one(document)
            outcome = "ok"
            saved_status.elapsed_ms = round((perf_counter() - started) * 1000, 3)
            return saved_status
        except (PyMongoError, HTTPException):
            return PersistenceStatus(status="error", message="Analysis completed, but the report could not be saved. MongoDB is unavailable.",
                                     elapsed_ms=round((perf_counter() - started) * 1000, 3))
        except Exception as error:
            capture_unexpected(error)
            return PersistenceStatus(status="error", message="Analysis completed, but report saving failed.",
                                     elapsed_ms=round((perf_counter() - started) * 1000, 3))
        finally:
            logging.getLogger("uvicorn.error").info("rivaliq_persistence outcome=%s elapsed_ms=%.3f", outcome, (perf_counter() - started) * 1000)

    async def list(self, limit: int, offset: int) -> ReportList:
        collection = self.require_collection()
        try:
            with stage("mongodb.list"):
                cursor = collection.find({}, {"summary": 1}).sort("_id", DESCENDING).skip(offset).limit(limit + 1)
                documents = await cursor.to_list(length=limit + 1)
            reports = [ReportSummary.model_validate(doc["summary"]) for doc in documents[:limit]]
            return ReportList(reports=reports, next_offset=offset + limit if len(documents) > limit and offset + limit <= 10000 else None)
        except (PyMongoError, ValidationError, KeyError):
            raise HTTPException(503, "Report history is temporarily unavailable.") from None

    async def get(self, report_id: str) -> SavedReport:
        if not re.fullmatch(r"[0-9a-fA-F]{24}", report_id):
            raise HTTPException(422, "Report ID must be a 24-character hexadecimal MongoDB ObjectId.")
        collection = self.require_collection()
        try:
            with stage("mongodb.get"):
                document = await collection.find_one({"_id": ObjectId(report_id)})
            if document is None:
                raise HTTPException(404, "Report not found.")
            return SavedReport.model_validate({"id": str(document["_id"]), **{key: document[key] for key in
                ("created_at", "schema_version", "seller_inputs", "intelligence")}})
        except (PyMongoError, ValidationError, KeyError):
            raise HTTPException(503, "The saved report could not be retrieved.") from None

    async def close(self):
        if self.client is not None:
            await self.client.close()


def create_report_store() -> ReportStore:
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        return ReportStore()
    client = None
    try:
        database = os.getenv("MONGODB_DATABASE", "rivaliq").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database):
            raise ValueError("Invalid database name")
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000, socketTimeoutMS=5000,
                                  timeoutMS=5000, retryWrites=True, tz_aware=True)
        return ReportStore(client[database]["reports"], client=client, configured=True,
            observation_collection=client[database]["price_observations"], secrets=(
            uri, os.getenv("SERPAPI_API_KEY", ""), os.getenv("SENTRY_DSN", ""), os.getenv("TABPFN_API_KEY", "")))
    except (PyMongoError, ValueError):
        logging.getLogger("uvicorn.error").warning("MongoDB configuration invalid; report saving unavailable.")
        return ReportStore(client=client, configured=True)
