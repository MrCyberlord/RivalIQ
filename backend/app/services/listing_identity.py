import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalized(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), ""))
