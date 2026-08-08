"""Secret redaction helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_KEY_PATTERN = re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([A-Za-z0-9]{8,})")


def redact_text(text: str) -> str:
    return _KEY_PATTERN.sub(r"\1<redacted>", text)


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "<redacted>" if key.lower() in {"api_key", "apikey", "key"} else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
