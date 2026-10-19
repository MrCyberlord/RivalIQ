from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import OllamaSettings, get_api_key, get_ollama_settings
from app.intelligence_schemas import IntelligenceRequest, IntelligenceResponse
from app.services.intelligence import analyze
from app.schemas import SearchRequest, SearchResponse
from app.services.serpapi import search_competitors
from app.services.reports import ReportStore, create_report_store
from app.report_schemas import ReportList, SavedReport
from app.observability import configure_sentry, flush_sentry
from app.services.observations import ObservationStore
from app.services.pricing import HostedRegressor, predict_pricing
from app.pricing_schemas import PredictionRequest, PredictionResponse

configure_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=20) as client:
        app.state.http_client = client
        app.state.report_store = create_report_store()
        app.state.observation_store = ObservationStore(app.state.report_store.observation_collection,
                                                       secrets=app.state.report_store.secrets)
        app.state.pricing_runner = HostedRegressor()
        try:
            yield
        finally:
            try:
                await app.state.report_store.close()
            finally:
                flush_sentry()


app = FastAPI(title="RivalIQ API", version="0.4.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.middleware("http")
async def measure_intelligence_request(request: Request, call_next):
    if request.url.path != "/api/intelligence":
        return await call_next(request)
    started = perf_counter()
    request.state.rival_request_id = uuid4().hex
    response = None
    try:
        response = await call_next(request)
        response.headers["Server-Timing"] = f"app;dur={(perf_counter() - started) * 1000:.3f}"
        return response
    finally:
        request_id = request.state.rival_request_id
        logging.getLogger("uvicorn.error").info("rivaliq_http request_id=%s status=%s total_ms=%.3f", request_id,
            response.status_code if response is not None else 500, (perf_counter() - started) * 1000)


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_report_store(request: Request) -> ReportStore:
    # A disabled store also keeps dependency-overridden, lifespan-free clients compatible.
    return getattr(request.app.state, "report_store", ReportStore())


def get_observation_store(request: Request) -> ObservationStore:
    return getattr(request.app.state, "observation_store", ObservationStore())


def get_pricing_runner(request: Request) -> HostedRegressor:
    return getattr(request.app.state, "pricing_runner", HostedRegressor())


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rivaliq-api"}


@app.post("/api/competitors/search", response_model=SearchResponse)
async def search(body: SearchRequest, api_key: str = Depends(get_api_key),
                 client: httpx.AsyncClient = Depends(get_http_client),
                 observations: ObservationStore = Depends(get_observation_store)) -> SearchResponse:
    return SearchResponse(competitors=await search_competitors(body, api_key, client, observations=observations))


@app.post("/api/intelligence", response_model=IntelligenceResponse)
async def intelligence(body: IntelligenceRequest, http_response: Response, http_request: Request, api_key: str = Depends(get_api_key),
                       client: httpx.AsyncClient = Depends(get_http_client),
                       settings: OllamaSettings = Depends(get_ollama_settings),
                       store: ReportStore = Depends(get_report_store),
                       observations: ObservationStore = Depends(get_observation_store)) -> IntelligenceResponse:
    result = await analyze(body, api_key, client, settings, request_id=http_request.state.rival_request_id, observations=observations)
    result.persistence = await store.save(body, result)
    if result.performance:
        http_response.headers["X-RivalIQ-Request-ID"] = result.performance.request_id
    return result


@app.get("/api/reports", response_model=ReportList)
async def list_reports(limit: int = Query(default=10, ge=1, le=50), offset: int = Query(default=0, ge=0, le=10000),
                       store: ReportStore = Depends(get_report_store)) -> ReportList:
    return await store.list(limit, offset)


@app.get("/api/reports/{report_id}", response_model=SavedReport)
async def get_report(report_id: str, store: ReportStore = Depends(get_report_store)) -> SavedReport:
    return await store.get(report_id)


@app.post("/api/pricing/predict", response_model=PredictionResponse)
async def pricing_prediction(body: PredictionRequest, store: ObservationStore = Depends(get_observation_store),
                             runner: HostedRegressor = Depends(get_pricing_runner)) -> PredictionResponse:
    return await predict_pricing(body, store, runner)
