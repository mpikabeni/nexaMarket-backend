"""Cours du GRAM (ex-Toncoin) en FCFA, relu sur le marché toutes les 10 minutes.

Telegram n'expose pas d'API publique de prix : on interroge les services de
cours de l'écosystème TON (tonapi.io, utilisé par les portefeuilles), avec
CoinGecko en secours. Le prix en USD est converti en FCFA avec le taux
USD/XAF (voir fx.py).

Un canal à prix en FCFA est ainsi payé en GRAM au cours du moment :
    prix en GRAM = prix en FCFA / (FCFA pour 1 GRAM)
Le montant est figé sur la transaction au moment où l'acheteur lance l'achat.
"""

from __future__ import annotations

import logging
import time
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy import select

from app.config import settings
from app.models.listing import Listing
from app.services import fx

logger = logging.getLogger("nexmarket.gram_rate")

# Au-delà, un cours en cache est jugé trop ancien pour être utilisé.
MAX_AGE_SECONDS = 24 * 3600
RETRY_SECONDS = 60

_cache: dict = {"usd": None, "fetched": 0.0, "tried": 0.0, "source": None}


class GramRateUnavailable(Exception):
    pass


def refresh_seconds() -> int:
    return max(60, int(settings.GRAM_RATE_REFRESH_SECONDS or 600))


def _plausible(usd: float) -> bool:
    # Garde-fou : écarte un prix absurde (ou un autre jeton homonyme).
    return 0.05 < usd < 1000


async def _from_tonapi(client: httpx.AsyncClient) -> float | None:
    for token in ("gram", "ton"):  # « ton » : ancien nom, au cas où
        try:
            response = await client.get(
                "https://tonapi.io/v2/rates",
                params={"tokens": token, "currencies": "usd"},
            )
            response.raise_for_status()
            rates = (response.json() or {}).get("rates") or {}
            for entry in rates.values():
                prices = {k.upper(): v for k, v in (entry.get("prices") or {}).items()}
                usd = float(prices.get("USD") or 0)
                if _plausible(usd):
                    return usd
        except Exception as exc:  # noqa: BLE001
            logger.warning("tonapi (%s) indisponible : %s", token, exc)
    return None


async def _from_coingecko(client: httpx.AsyncClient) -> float | None:
    try:
        response = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "the-open-network", "vs_currencies": "usd"},
        )
        response.raise_for_status()
        usd = float(((response.json() or {}).get("the-open-network") or {}).get("usd") or 0)
        return usd if _plausible(usd) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("CoinGecko indisponible : %s", exc)
        return None


async def _refresh() -> bool:
    now = time.time()
    _cache["tried"] = now
    async with httpx.AsyncClient(timeout=6.0) as client:
        for name, source in (("tonapi.io", _from_tonapi), ("coingecko.com", _from_coingecko)):
            usd = await source(client)
            if usd:
                _cache.update(usd=usd, fetched=now, source=name)
                logger.info("Cours GRAM : %s USD (%s)", usd, name)
                return True
    return False


async def get_rate(force: bool = False) -> dict | None:
    """Cours actuel : {xaf_per_gram, usd, source, fetched} ou None si inconnu."""

    manual = float(settings.GRAM_XAF_RATE or 0)
    if manual > 0:
        return {"xaf_per_gram": manual, "usd": None, "source": "manuel", "fetched": time.time()}

    now = time.time()
    stale = now - _cache["fetched"] > refresh_seconds()
    may_retry = now - _cache["tried"] > RETRY_SECONDS
    if force or (stale and may_retry):
        await _refresh()

    usd = _cache["usd"]
    if not usd or time.time() - _cache["fetched"] > MAX_AGE_SECONDS:
        return None

    xaf_per_usd, _ = await fx.get_xaf_per_usd()
    if not xaf_per_usd:
        return None

    return {
        "xaf_per_gram": usd * xaf_per_usd,
        "usd": usd,
        "source": _cache["source"],
        "fetched": _cache["fetched"],
    }


def xaf_to_gram(xaf, rate: dict) -> Decimal:
    """Prix en GRAM (2 décimales) pour un prix en FCFA, au cours donné."""

    value = Decimal(str(xaf)) / Decimal(str(rate["xaf_per_gram"]))
    return max(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), Decimal("0.01"))


async def quote(xaf) -> tuple[Decimal, dict]:
    rate = await get_rate()
    if not rate:
        raise GramRateUnavailable(
            "Le cours du GRAM est momentanément indisponible. Réessayez dans un instant."
        )
    return xaf_to_gram(xaf, rate), rate


async def refresh_listing_prices(session_factory) -> int:
    """Remet à jour le prix en GRAM des annonces dont le prix est fixé en FCFA."""

    rate = await get_rate()
    if not rate:
        return 0

    changed = 0
    async with session_factory() as db:
        listings = (
            await db.execute(
                select(Listing).where(
                    Listing.currency == "GRAM",
                    Listing.price_xaf.is_not(None),
                    Listing.status.in_(("pending_review", "approved", "published")),
                )
            )
        ).scalars().all()
        for listing in listings:
            new_price = xaf_to_gram(listing.price_xaf, rate)
            if new_price != listing.price:
                listing.price = new_price
                changed += 1
        if changed:
            await db.commit()
    return changed
