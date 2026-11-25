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

from app.services import gram_service

router = APIRouter(prefix="/rates", tags=["Rates"])
logger = logging.getLogger("nexmarket.rates")

EUR_XAF = 655.957
CACHE_SECONDS = 6 * 3600
RETRY_SECONDS = 300
SOURCE_URL = "https://open.er-api.com/v6/latest/USD"

_cache: dict = {"xaf_per_usd": None, "fetched": 0.0, "tried": 0.0, "source": None, "table": {}}


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
        raw = data.get("rates") or {}
        rate = float(raw.get("XAF") or 0)
        # Toutes les devises (unités pour 1 USD) : sert aux prix des annonces GRAM.
        table = {
            str(code).upper(): float(value)
            for code, value in raw.items()
            if isinstance(code, str) and len(code) == 3 and isinstance(value, (int, float)) and value > 0
        }
        # Garde-fou : un taux absurde n'est jamais publié.
        if 300 < rate < 1500:
            _cache.update(xaf_per_usd=rate, fetched=now, source="open.er-api.com", table=table)
        else:
            logger.warning("Taux USD/XAF ignoré (valeur suspecte) : %s", rate)
    except Exception as exc:  # réseau, JSON, etc.
        logger.warning("Taux USD/XAF indisponible : %s", exc)


async def _usd_xaf() -> tuple[float | None, str | None]:
    manual = _manual_rate()
    now = time.time()

    if manual:
        return manual, "manuel"

    stale = now - _cache["fetched"] > CACHE_SECONDS
    may_retry = now - _cache["tried"] > RETRY_SECONDS

    if stale and may_retry:
        await _refresh()

    return _cache["xaf_per_usd"], _cache["source"]


async def usd_table() -> dict[str, float]:
    """Unités de chaque devise pour 1 USD (XAF/XOF/EUR alignés sur le taux officiel)."""

    xaf_per_usd, _source = await _usd_xaf()
    table = dict(_cache.get("table") or {})

    if xaf_per_usd:
        table["XAF"] = table["XOF"] = xaf_per_usd
        table["EUR"] = xaf_per_usd / EUR_XAF

    table["USD"] = 1.0
    return table


@router.get("")
async def get_rates():
    xaf_per_usd, source = await _usd_xaf()

    # Cours du GRAM : mis à jour toutes les 10 minutes (compte à rebours côté appli).
    from app.services import gram_price

    gram_usd, gram_fetched, gram_source = await gram_price.get_gram_usd()
    gram_xaf = await gram_price.get_gram_xaf() if gram_usd else None
    table = await usd_table()

    return {
        "gram": {
            "usd": gram_usd,
            "xaf": float(gram_xaf) if gram_xaf else None,
            "updated_at": gram_fetched or None,
            "next_refresh_at": (gram_fetched + gram_price.REFRESH_SECONDS) if gram_fetched else None,
            "interval_seconds": gram_price.REFRESH_SECONDS,
            "source": gram_source,
            # Devises utilisables pour fixer un prix d'annonce GRAM (unités pour 1 USD).
            "usd_table": {k: round(v, 6) for k, v in table.items()},
        },
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
        # Le paiement en GRAM est-il configuré (adresse de NexMarket valide) ?
        "gram_enabled": gram_service.enabled(),
    }
