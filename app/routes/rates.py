"""Taux de change PUBLICS, pour l'AFFICHAGE en Euro / Dollar.

Les montants réels (soldes, dépôts, retraits, commissions) restent en XAF :
ces taux ne servent qu'à montrer une valeur indicative à l'utilisateur.

- EUR : parité FIXE du franc CFA (1 EUR = 655,957 XAF), jamais d'appel externe.
- USD : taux récupéré sur open.er-api.com (sans clé), mis en cache 6 h ;
  en cas d'échec on garde le dernier taux connu. Variable Render optionnelle
  USD_XAF_RATE (nombre de XAF pour 1 USD) pour imposer un taux manuel.
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/rates", tags=["Rates"])
logger = logging.getLogger("nexmarket.rates")

EUR_XAF = 655.957
CACHE_SECONDS = 6 * 3600
RETRY_SECONDS = 300
SOURCE_URL = "https://open.er-api.com/v6/latest/USD"

_cache: dict = {"xaf_per_usd": None, "fetched": 0.0, "tried": 0.0, "source": None}


def _manual_rate() -> float | None:
    try:
        value = float(os.environ.get("USD_XAF_RATE", "") or 0)
    except ValueError:
        return None
    return value if value > 0 else None


async def _refresh() -> None:
    now = time.time()
    _cache["tried"] = now
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(SOURCE_URL)
            response.raise_for_status()
            data = response.json()
        rate = float((data.get("rates") or {}).get("XAF") or 0)
        # Garde-fou : un taux absurde n'est jamais publié.
        if 300 < rate < 1500:
            _cache.update(xaf_per_usd=rate, fetched=now, source="open.er-api.com")
        else:
            logger.warning("Taux USD/XAF ignoré (valeur suspecte) : %s", rate)
    except Exception as exc:  # réseau, JSON, etc.
        logger.warning("Taux USD/XAF indisponible : %s", exc)


@router.get("")
async def get_rates():
    manual = _manual_rate()
    now = time.time()

    if manual:
        xaf_per_usd, source = manual, "manuel"
    else:
        stale = now - _cache["fetched"] > CACHE_SECONDS
        may_retry = now - _cache["tried"] > RETRY_SECONDS
        if stale and may_retry:
            await _refresh()
        xaf_per_usd, source = _cache["xaf_per_usd"], _cache["source"]

    return {
        "base": "XAF",
        # unités de chaque devise pour 1 XAF
        "rates": {
            "XAF": 1,
            "XOF": 1,
            "EUR": 1 / EUR_XAF,
            "USD": (1 / xaf_per_usd) if xaf_per_usd else None,
        },
        "usd_source": source,
        "updated_at": _cache["fetched"] or None,
        "indicative": True,
    }
