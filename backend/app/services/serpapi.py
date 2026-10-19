import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from app.schemas import MARKETS, Competitor, SearchRequest
from app.observability import stage


def text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def price(value: object) -> float | None:
    # Only trust SerpApi's extracted numeric value; never guess from display text.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def currency(row: dict) -> str | None:
    display = text(row.get("price")) or ""
    explicit = text(row.get("currency"))
    if explicit and re.fullmatch(r"[A-Za-z]{3}", explicit):
        return explicit.upper()
    for token, code in (("₹", "INR"), ("US$", "USD"), ("CA$", "CAD"), ("A$", "AUD"), ("£", "GBP")):
        if token in display:
            return code
    match = re.search(r"\b(INR|USD|GBP|CAD|AUD)\b", display)
    return match.group(1) if match else None


def product_url(row: dict) -> str | None:
    for field in ("product_link", "link"):
        value = text(row.get(field))
        if value:
            try:
                parsed = urlparse(value)
            except ValueError:
                continue
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return value
    return None


async def search_competitors(request: SearchRequest, api_key: str, client: httpx.AsyncClient, *, observations=None, search_id=None) -> list[Competitor]:
    if not api_key:
        raise HTTPException(503, "Competitor search is not configured. Set SERPAPI_API_KEY in backend/.env.")
    try:
        with stage("serpapi.discovery"):
            response = await client.get("https://serpapi.com/search.json", params={
                "engine": "google_shopping", "q": request.product_name,
                "gl": MARKETS[request.market], "hl": "en", "api_key": api_key,
            })
        if response.status_code == 429:
            raise HTTPException(429, "Search provider rate limit reached. Try again later.")
        if response.status_code in (401, 403):
            raise HTTPException(503, "Search provider credentials were rejected.")
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException:
        raise HTTPException(504, "Search provider timed out.") from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Search provider returned an invalid response or is unavailable.") from None
    if not isinstance(payload, dict):
        raise HTTPException(502, "Search provider returned an invalid response.")
    error = payload.get("error")
    if error:
        message = str(error).lower()
        if any(word in message for word in ("rate limit", "run out", "quota", "too many")):
            raise HTTPException(429, "Search provider quota or rate limit reached.")
        raise HTTPException(502, "Search provider could not complete the search.")
    rows = payload.get("shopping_results", [])
    if not isinstance(rows, list):
        raise HTTPException(502, "Search provider returned invalid shopping results.")
    retrieved_at = datetime.now(timezone.utc)
    results = []
    for row in rows:
        if not isinstance(row, dict) or not row:
            continue
        extensions = row.get("extensions")
        features = [s for item in extensions if (s := text(item))] if isinstance(extensions, list) else None
        item = Competitor(
            product_name=text(row.get("title")), listed_price=price(row.get("extracted_price")),
            currency=currency(row), merchant=text(row.get("source")), product_url=product_url(row),
            retrieved_at=retrieved_at, features=features or None,
        )
        pid = row.get("product_id")
        if isinstance(pid, (str, int)) and not isinstance(pid, bool):
            item._source_product_id = str(pid).strip()[:200] or None
        results.append(item)
        if len(results) >= request.max_results:
            break
    if observations is not None:
        await observations.capture(results, request.market, search_id)
    return results
