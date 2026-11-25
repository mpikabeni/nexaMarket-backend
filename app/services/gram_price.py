"""Cours du GRAM (ex-Toncoin) et prix des annonces payées en GRAM.

Option « prix en FCFA qui suit le cours » :
- le vendeur fixe son prix en FCFA (listing.price_xaf) ;
- le montant en GRAM (listing.price) est recalculé toutes les 10 minutes
  avec le cours du moment ;
- à l'achat, le prix est recalculé UNE dernière fois : la transaction fige
  alors le montant exact que l'acheteur doit envoyer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from decimal import ROUND_CEILING, Decimal

import httpx
from sqlalchemy import select

logger = logging.getLogger("nexmarket.gram_price")

REFRESH_SECONDS = 600  # 10 minutes
RETRY_SECONDS = 60

# Cours MONDIAL : médiane de plusieurs sources (CoinGecko = agrégat mondial,
# Gate, Binance, OKX, Coinbase). Le Toncoin a été renommé GRAM : l'identifiant
# CoinGecko actuel est « gram » (GRAM_COINGECKO_ID pour le changer).
COINGECKO_ID = os.environ.get("GRAM_COINGECKO_ID", "gram").strip() or "gram"

SOURCES = (
    ("coingecko", f"https://api.coingecko.com/api/v3/simple/price?ids={COINGECKO_ID}&vs_currencies=usd"),
    ("gate", "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=GRAM_USDT"),
    ("binance", "https://api.binance.com/api/v3/ticker/price?symbol=GRAMUSDT"),
    ("okx", "https://www.okx.com/api/v5/market/ticker?instId=GRAM-USDT"),
    ("coinbase", "https://api.coinbase.com/v2/prices/GRAM-USD/spot"),
)

_cache: dict = {"usd": None, "fetched": 0.0, "tried": 0.0, "source": None}


def _extract(name: str, data) -> float:
    try:
        if name == "coingecko":
            return float(((data or {}).get(COINGECKO_ID) or {}).get("usd") or 0)
        if name == "gate":
            return float((data[0] if isinstance(data, list) and data else {}).get("last") or 0)
        if name == "coinbase":
            return float(((data or {}).get("data") or {}).get("amount") or 0)
        if name == "okx":
            rows = (data or {}).get("data") or [{}]
            return float((rows[0] or {}).get("last") or 0)
        return float((data or {}).get("price") or 0)  # binance
    except (TypeError, ValueError, AttributeError, IndexError):
        return 0.0


async def _fetch_source(client, name: str, url: str) -> tuple[str, float]:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return name, _extract(name, response.json())
    except Exception as exc:
        logger.warning("Cours GRAM indisponible (%s) : %s", name, exc)
        return name, 0.0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


async def _refresh() -> None:
    now = time.time()
    _cache["tried"] = now

    async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": "NexMarket/1.0"}) as client:
        results = await asyncio.gather(*(_fetch_source(client, n, u) for n, u in SOURCES))

    # Garde-fou : on ne garde que les cours plausibles.
    good = [(n, v) for n, v in results if 0.05 < v < 500]

    if not good:
        return

    values = [v for _n, v in good]
    center = _median(values)

    # Avec 3 sources ou plus, une source qui s'écarte de plus de 8 % de la
    # médiane (cours figé, mauvais symbole) est écartée.
    if len(good) >= 3:
        good = [(n, v) for n, v in good if abs(v - center) / center <= 0.08]
        center = _median([v for _n, v in good])

    names = "+".join(n for n, _v in good)
    _cache.update(usd=center, fetched=now, source=f"médiane mondiale ({names})")


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


def next_refresh_at() -> float | None:
    """Prochain rafraîchissement RÉEL : 10 min après la dernière mise à jour
    réussie, ou 1 min après la dernière tentative si le cours est en retard
    (sinon le compte à rebours resterait bloqué à 00:00)."""

    fetched = _cache["fetched"]

    if not fetched:
        return None

    due = fetched + REFRESH_SECONDS

    if time.time() < due:
        return due

    return max(_cache["tried"], time.time()) + RETRY_SECONDS
