"""Taux USD/XAF partagé (affichage USD + conversion du GRAM en FCFA).

- Récupéré sur open.er-api.com (sans clé), mis en cache 6 h ;
  en cas d'échec on garde le dernier taux connu.
- Variable Render optionnelle USD_XAF_RATE (FCFA pour 1 USD) : taux manuel.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

logger = logging.getLogger("nexmarket.fx")

CACHE_SECONDS = 6 * 3600
RETRY_SECONDS = 300
SOURCE_URL = "https://open.er-api.com/v6/latest/USD"

cache: dict = {"xaf_per_usd": None, "fetched": 0.0, "tried": 0.0, "source": None}


def manual_rate() -> float | None:
    try:
        value = float(os.environ.get("USD_XAF_RATE", "") or 0)
    except ValueError:
        return None
    return value if value > 0 else None


async def _refresh() -> None:
    now = time.time()
    cache["tried"] = now
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(SOURCE_URL)
            response.raise_for_status()
            data = response.json()
        rate = float((data.get("rates") or {}).get("XAF") or 0)
        # Garde-fou : un taux absurde n'est jamais publié.
        if 300 < rate < 1500:
            cache.update(xaf_per_usd=rate, fetched=now, source="open.er-api.com")
        else:
            logger.warning("Taux USD/XAF ignoré (valeur suspecte) : %s", rate)
    except Exception as exc:  # réseau, JSON, etc.
        logger.warning("Taux USD/XAF indisponible : %s", exc)


async def get_xaf_per_usd() -> tuple[float | None, str | None]:
    """(FCFA pour 1 USD, source) — None si aucun taux n'est connu."""

    manual = manual_rate()
    if manual:
        return manual, "manuel"

    now = time.time()
    stale = now - cache["fetched"] > CACHE_SECONDS
    may_retry = now - cache["tried"] > RETRY_SECONDS
    if stale and may_retry:
        await _refresh()
    return cache["xaf_per_usd"], cache["source"]
