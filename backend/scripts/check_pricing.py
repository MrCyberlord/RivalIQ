"""Check real historical data; hosted inference requires --allow-cloud-processing.

Never creates observations, backfills prices, reruns discovery, or prints credentials.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.config  # load backend/.env without displaying its contents
from app.pricing_schemas import PredictionRequest
from app.services.observations import ObservationStore
from app.services.pricing import HostedRegressor, predict_pricing
from app.services.reports import create_report_store


async def check(args):
    report_store = create_report_store()
    try:
        result = await predict_pricing(PredictionRequest(attributes={"brand": args.brand, "category": args.category,
            "capacity_ml": args.capacity_ml, "material": args.material}, currency=args.currency, market=args.market,
            allow_cloud_processing=args.allow_cloud_processing),
            ObservationStore(report_store.observation_collection, secrets=report_store.secrets), HostedRegressor())
        output = result.model_dump(mode="json", exclude={"sources", "limitations"})
        output.update(api_key_configured=bool(os.getenv("TABPFN_API_KEY", "").strip()),
                      hosted_processing_requested=args.allow_cloud_processing)
        print(json.dumps(output, indent=2))
    finally:
        await report_store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", default="milton")
    parser.add_argument("--category", default="bottle")
    parser.add_argument("--capacity-ml", default="1000")
    parser.add_argument("--material", default="stainless steel")
    parser.add_argument("--currency", default="INR")
    parser.add_argument("--market", default="India")
    parser.add_argument("--allow-cloud-processing", action="store_true")
    asyncio.run(check(parser.parse_args()))
