"""Verifying that a request really came from Retell (X-Retell-Signature).

Per Retell's docs ("Secure the webhook", "Verify Without SDK"):
- the header looks like  v=<unix ms>,d=<hex digest>
- digest = HMAC-SHA256(key=<Retell API key>, message=<raw body> + <timestamp string>)
- the timestamp must be within 5 minutes of now (stops replays)
- always use the raw body bytes as received, never re-serialised JSON
The same check covers both the webhook and custom-function calls.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Optional

HEADER = "X-Retell-Signature"
TOLERANCE_MS = 5 * 60 * 1000
_PATTERN = re.compile(r"v=(\d+),d=(.*)")


def sign(raw_body: str, api_key: str, timestamp_ms: Optional[int] = None) -> str:
    """Build a header value the way Retell does (used by the tests and the local simulator)."""
    ts = str(int(time.time() * 1000) if timestamp_ms is None else timestamp_ms)
    digest = hmac.new(api_key.encode(), (raw_body + ts).encode(), hashlib.sha256).hexdigest()
    return f"v={ts},d={digest}"


def verify(raw_body: str, api_key: str, signature: Optional[str], now_ms: Optional[int] = None,
           tolerance_ms: int = TOLERANCE_MS) -> bool:
    if not api_key or not signature:
        return False
    m = _PATTERN.fullmatch(signature.strip())
    if not m:
        return False
    ts, digest = m.group(1), m.group(2)
    now = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(now - int(ts)) > tolerance_ms:
        return False
    expected = hmac.new(api_key.encode(), (raw_body + ts).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest.lower())
