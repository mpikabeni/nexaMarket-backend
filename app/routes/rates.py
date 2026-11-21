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
import time

from fastapi import APIRouter

from app.services import fx, gram_rate, gram_service

router = APIRouter(prefix="/rates", tags=["Rates"])
logger = logging.getLogger("nexmarket.rates")

EUR_XAF = 655.957


@router.get("")
async def get_rates():
    xaf_per_usd, source = await fx.get_xaf_per_usd()
    gram = await gram_rate.get_rate()
    refresh = gram_rate.refresh_seconds()
    next_in = None
    if gram and gram.get("fetched"):
        next_in = max(0, int(gram["fetched"] + refresh - time.time()))

    return {
        "base": "XAF",
        # unités de chaque devise pour 1 XAF
        "rates": {
            "XAF": 1,
            "XOF": 1,
            "EUR": 1 / EUR_XAF,
            "USD": (1 / xaf_per_usd) if xaf_per_usd else None,
            "GRAM": (1 / gram["xaf_per_gram"]) if gram else None,
        },
        "usd_source": source,
        "updated_at": fx.cache["fetched"] or None,
        "indicative": True,
        # Le paiement en GRAM est-il configuré (adresse de NexMarket valide) ?
        "gram_enabled": gram_service.enabled(),
        # Cours du GRAM relu sur le marché toutes les 10 min.
        "gram": {
            "xaf_per_gram": gram["xaf_per_gram"] if gram else None,
            "usd": gram["usd"] if gram else None,
            "source": gram["source"] if gram else None,
            "updated_at": gram["fetched"] if gram else None,
            "refresh_seconds": refresh,
            "next_refresh_in": next_in,
        },
    }
