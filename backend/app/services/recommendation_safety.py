"""Conservative language guardrails, not semantic verification or another model.

Competitors are evidence only. Numeric proposed price targets are withheld even
when equal to an observed price: observation alone cannot justify that target.
Contextual observed prices and seller-directed review/promotion advice remain valid.
"""
import re
from decimal import Decimal, InvalidOperation

from app.intelligence_schemas import EvidenceQuality, Finding, RecommendationSafety


def evidence_quality(pricing):
    count = pricing.comparable_price_count
    band, explanation = (
        ("none", "No comparable offers: reliable like-for-like pricing guidance is unavailable.") if count == 0 else
        ("single", "One comparable offer is an individual observation, not a market benchmark.") if count == 1 else
        ("small", "Two to four comparable offers support directional comparisons only; this is a small sample.") if count < 5 else
        ("descriptive", "Five or more comparable offers support descriptive comparisons, not statistical representativeness.")
    )
    return EvidenceQuality(sample_size=count, band=band, explanation=explanation,
                           source_ids=[c.source_id for c in pricing.comparisons])


ACTION = r"(?:reduc\w*|lower\w*|increas\w*|rais\w*|maintain\w*|keep\w*|set\w*|adjust\w*|chang\w*|updat\w*|discount\w*|promot\w*|price\w*|reprice\w*)"
CONTROL = re.compile(rf"\b{ACTION}\s+(?:(?:the|a|an)\s+)?(?:(?:listing|prices?\s+(?:of|for))\s+)?(?:L\d+\b|competitor\b|competitors\b|their\b)", re.I)
REFERENCE = re.compile(r"\bL\d+\b", re.I)
SELLER = re.compile(r"\b(?:your|you|seller(?:'s|’s)?)\b", re.I)
PROMISE = re.compile(r"\b(?:guarantee\w*|ensure\w*|certain\w*|will|always|proven|optimal|best[- ]selling|profit[- ]maximi\w*)\b.{0,55}\b(?:profit\w*|sales|demand|sell\w*|advantage\w*|win\w*|conversion\w*)\b|\b(?:sales|profits?|demand)\s+will\b|\b(?:optimal|profit[- ]maximi\w*)\s+(?:price|pricing)\b", re.I)
TARGET = re.compile(r"\b(?:reduce|lower|increase|raise|set|maintain|keep|price|reprice|discount|sell|offer|test|match)\w*\b[^.;!?]{0,100}\b(?:to|at|by|for)\s+(?:(?:INR|USD|GBP|CAD|AUD|Rs\.?)\s*|[₹$£]\s*)?(?:\d|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b)", re.I)
EXPLICIT_TARGET = re.compile(r"\b(?:set|reduce|lower|raise|increase|reprice|discount)\w*\b[^.;!?]{0,60}\b(?:your|seller|price)\b[^.;!?]{0,60}\d", re.I)
IMPLIED_TARGET = re.compile(r"\b(?:your|seller(?:'s)?)\b[^.;!?]{0,35}\bprice\b[^.;!?]{0,20}\b(?:should be|must be|ought to be|target)\b[^.;!?]{0,30}\d", re.I)


def rejection_reason(draft, listings, pricing):
    if set(draft) - {"text", "source_ids"}:
        return "invalid_structure"
    text, refs = draft.get("text"), draft.get("source_ids")
    available = {l.id for l in listings if not l.duplicate_of}
    if not isinstance(text, str) or not text.strip() or len(text) > 600:
        return "invalid_text"
    if (not isinstance(refs, list) or not refs or len(refs) > 12 or
            any(not isinstance(ref, str) or ref not in available for ref in refs) or
            any(ref.upper() not in refs for ref in REFERENCE.findall(text))):
        return "invalid_citation"
    if CONTROL.search(text) or not SELLER.search(text):
        return "not_seller_directed"
    if PROMISE.search(text) or (re.search(r"\b(?:boost|drive|grow|increase|improve|maximi[sz]e)\w*\b.{0,40}\b(?:sales|profits?|demand|conversions?)\b", text, re.I)
            and not re.search(r"\b(?:measure|track|test whether|evaluate whether)\b", text, re.I)):
        return "unsupported_outcome_claim"
    numeric_text = REFERENCE.sub("", text)
    if TARGET.search(numeric_text) or EXPLICIT_TARGET.search(numeric_text) or IMPLIED_TARGET.search(numeric_text):
        return "unsupported_price_target"
    # Bare numbers must be observed monetary values or explicitly stated unit
    # quantities. This rejects invented monetary figures and percentage promises.
    context = REFERENCE.sub("", text)
    context = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ml|litres?|liters?|l|grams?|g|kg)\b", "", context, flags=re.I)
    allowed = {pricing.selling_price, *([pricing.cost] if pricing.cost is not None else [])}
    allowed.update(Decimal(str(l.listed_price)) for l in listings if l.id in refs and l.listed_price is not None and l.currency == pricing.currency)
    for number in re.findall(r"(?<!\w)\d[\d,]*(?:\.\d+)?\s*%?", context):
        if "%" in number:
            return "unsupported_numerical_claim"
        try:
            if Decimal(number.replace(",", "").strip()) not in allowed:
                return "unsupported_numerical_claim"
        except InvalidOperation:
            return "unsupported_numerical_claim"
    # Never promote broader/unknown matches into a seller pricing conclusion.
    if (pricing.comparable_price_count == 0 and re.search(r"\bpric\w*\b", text, re.I)
            and re.search(r"\b(?:against|versus|relative to|compared|compare)\b", text, re.I)
            and not re.search(r"\b(?:before|confirm|verify|unavailable|unknown|cannot|no comparable)\b", text, re.I)):
        return "insufficient_comparable_evidence"
    if (re.search(r"\b(?:cheaper|overpriced|underpriced|premium|undercut|below|above)\b", text, re.I)
            or re.search(r"\b(?:use|follow|match|rely on)\b.{0,30}\bbenchmark\b", text, re.I)):
        comparable = {c.source_id for c in pricing.comparisons}
        if not set(refs).issubset(comparable) or pricing.comparable_price_count < 2:
            return "insufficient_comparable_evidence"
    return None


def safe_recommendations(drafts, listings, pricing):
    quality = evidence_quality(pricing)
    unique = [l.id for l in listings if not l.duplicate_of]
    evidence = quality.source_ids or unique
    # The pipeline refuses empty discoveries before reaching this function.
    refs = evidence[:12]
    first = {
        "none": "Gather attribute-matched offers before changing your price; reliable like-for-like pricing guidance is unavailable.",
        "single": "Verify the single comparable offer against your product; treat its price as one observation, not a market benchmark.",
        "small": "Review your current price against the comparable offers; use this small sample only for directional comparisons.",
        "descriptive": "Review your current price against comparable offers; this descriptive sample is not statistically representative.",
    }[quality.band]
    fallbacks = [first,
        "Check your product's stated category, capacity, material and brand against the cited listings; confirm unknown specifications before repositioning.",
        "Consider testing a promotion for your product only after confirming equivalence, your costs, shipping, taxes and fees; no sales or profit outcome is assured."]
    result, reasons, used = [], [], set()
    for index in range(3):
        draft = drafts[index] if index < len(drafts) else {}
        reason = rejection_reason(draft, listings, pricing)
        if not reason and draft["text"].strip().casefold() in used:
            reason = "duplicate_action"
        if reason:
            reasons.append(reason)
            finding = Finding(text=fallbacks[index], source_ids=refs)
        else:
            finding = Finding.model_validate(draft)
        used.add(finding.text.casefold())
        result.append(finding)
    return result, RecommendationSafety(status="adjusted" if reasons else "passed", replaced_count=len(reasons),
        reason_codes=sorted(set(reasons)), message=(
            "Unsafe or unsupported recommendations were replaced with deterministic seller guidance; this is not new AI analysis."
            if reasons else "Recommendations passed conservative seller-direction, citation and pricing checks; claims remain unverified."))
