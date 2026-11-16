"""Vérification de la signature des webhooks JessiKaPay (doc : HMAC-SHA256)."""

from __future__ import annotations

import hashlib
import hmac
import time


def verify_signature(secret: str, timestamp: str, signature: str, raw_body: bytes, *, now: float | None = None) -> bool:
    """True seulement si le timestamp est frais (±5 min) et la signature exacte.

    Signature = HMAC-SHA256 hex de « {timestamp}.{corps brut} » avec l'api_secret.
    """

    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - ts) > 300:
        return False
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())
