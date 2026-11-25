"""Cours du GRAM (ex-Toncoin) et prix des annonces payées en GRAM.

Option « prix en FCFA qui suit le cours » :
- le vendeur fixe son prix en FCFA (listing.price_xaf) ;
- le montant en GRAM (listing.price) est recalculé toutes les 10 minutes
  avec le cours du moment ;
- à l'achat, le prix est recalculé UNE dernière fois : la transaction fige
  alors le montant exact que l'acheteur doit envoyer.
"""

from __future__ import annotations

import logging
import os
import time
from decimal import ROUND_CEILING, Decimal

import httpx
from sqlalchemy import select

logger = logging.getLogger("nexmarket.gram_price")

REFRESH_SECONDS = 600  # 10 minutes
RETRY_SECONDS = 60

# CoinGecko d'abord, Binance en secours. GRAM_USD_PRICE (env) force un cours.
SOURCES = (
    ("coingecko", "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd"),
    ("binance", "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT"),
)

_cache: dict = {"usd": None, "fetched": 0.0, "tried": 0.0, "source": None}


def _extract(name: str, data) -> float:
    if name == "coingecko":
        return float(((data or {}).get("the-open-network") or {}).get("usd") or 0)
    return float((data or {}).get("price") or 0)


async def _refresh() -> None:
    now = time.time()
    _cache["tried"] = now

    for name, url in SOURCES:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                value = _extract(name, response.json())
            # Garde-fou : un cours absurde n'est jamais utilisé.
            if 0.05 < value < 500:
                _cache.update(usd=value, fetched=now, source=name)
                return
            logger.warning("Cours GRAM ignoré (%s, valeur suspecte) : %s", name, value)
        except Exception as exc:
            logger.warning("Cours GRAM indisponible (%s) : %s", name, exc)


async def get_gram_usd() -> tuple[float | None, float, str | None]:
    """(cours USD, instant de la dernière mise à jour, source)."""

    try:
        manual = float(os.environ.get("GRAM_USD_PRICE", "") or 0)
    except ValueError:
        manual = 0

    if manual > 0:
        return manual, time.time(), "manuel"

    now = time.time()
    stale = now - _cache["fetched"] >= REFRESH_SECONDS
    may_retry = now - _cache["tried"] >= RETRY_SECONDS

    if stale and may_retry:
        await _refresh()

    return _cache["usd"], _cache["fetched"], _cache["source"]


async def get_gram_xaf() -> Decimal | None:
    """Valeur d'1 GRAM en FCFA, ou None si le cours est inconnu."""

    from app.routes.rates import usd_table

    usd, _fetched, _src = await get_gram_usd()
    xaf_per_usd = (await usd_table()).get("XAF")

    if not usd or not xaf_per_usd:
        return None

    return Decimal(str(usd)) * Decimal(str(xaf_per_usd))


async def gram_for(price, currency: str = "XAF") -> Decimal | None:
    """Montant en GRAM (arrondi au centième SUPÉRIEUR) pour un prix dans
    n'importe quelle devise connue. None si le cours ou la devise est inconnu."""

    from app.routes.rates import usd_table

    usd, _fetched, _src = await get_gram_usd()
    units_per_usd = (await usd_table()).get((currency or "XAF").upper())

    if not usd or not units_per_usd:
        return None

    amount_usd = Decimal(str(price)) / Decimal(str(units_per_usd))

    return (amount_usd / Decimal(str(usd))).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


async def gram_for_xaf(price_xaf: Decimal) -> Decimal | None:
    return await gram_for(price_xaf, "XAF")


async def refresh_listing(listing) -> bool:
    """Recalcule le prix GRAM d'une annonce dont le prix de base est dans une devise."""

    if (listing.currency or "").upper() != "GRAM" or not listing.price_xaf:
        return False

    new_price = await gram_for(listing.price_xaf, getattr(listing, "base_currency", None) or "XAF")

    if new_price is None or new_price < Decimal("0.01"):
        return False  # cours inconnu : on garde le dernier prix

    if Decimal(listing.price) != new_price:
        listing.price = new_price
        return True

    return False


async def refresh_all(session_factory) -> int:
    """Met à jour toutes les annonces GRAM actives (toutes les 10 min)."""

    from app.models.listing import Listing

    changed = 0

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(Listing).where(
                    Listing.currency == "GRAM",
                    Listing.price_xaf.is_not(None),
                    Listing.status.in_(("published", "pending_review")),
                )
            )
        ).scalars().all()

        for listing in rows:
            if await refresh_listing(listing):
                changed += 1

        if changed:
            await db.commit()

    return changed
