"""Explicit live smoke check: up to two paid SerpApi searches and two local model calls.

Run from the repository root. This is deliberately not part of the mocked test suite.
Only timing metadata, counts and benchmark status are printed, never credentials or prompts.
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from time import perf_counter

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_api_key, get_ollama_settings
from app.intelligence_schemas import IntelligenceRequest
from app.services.intelligence import analyze


async def run(args):
    started = perf_counter()
    try:
        request = IntelligenceRequest(product_name=args.product, selling_price=args.selling_price,
                                      cost=args.cost, max_results=args.max_results)
        async with httpx.AsyncClient(timeout=20) as client:
            result = await analyze(request, get_api_key(), client, get_ollama_settings())
        print(json.dumps({"status": "ok", "wall_ms": round((perf_counter() - started) * 1000, 3),
            "listing_count": len(result.listings), "comparable_price_count": result.pricing.comparable_price_count,
            "benchmark_status": result.pricing.benchmark_status, "recommendations": len(result.report.recommendations),
            "performance": result.performance.model_dump(mode="json")}, indent=2))
    except HTTPException as error:
        print(json.dumps({"status": "error", "http_status": error.status_code, "detail": error.detail,
                          "wall_ms": round((perf_counter() - started) * 1000, 3)}))
        return 1
    return 0


if __name__ == "__main__":
    # Enable only our allowlisted logger, never HTTPX URL logs with query credentials.
    logger = logging.getLogger("uvicorn.error")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())
    logger.propagate = False
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", default="Milton stainless steel water bottle 1 litre")
    parser.add_argument("--selling-price", default="799.00")
    parser.add_argument("--cost", default="500.00")
    parser.add_argument("--max-results", type=int, choices=range(1, 7), default=5)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
