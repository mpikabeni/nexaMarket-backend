"""Statistiques PUBLIQUES de la page d'accueil (confiance des utilisateurs)."""

from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import func, select

from app.deps import DBSession
from app.models.channel import Channel
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.user import User

router = APIRouter(prefix="/stats", tags=["Stats"])

# Statuts d'une transaction « en cours » (payée, pas encore terminée).
ACTIVE_STATUSES = (
    "waiting_admin",
    "transfer_started",
    "protection_period",
    "disputed",
)

_CACHE: dict = {"until": 0.0, "data": None}
_CACHE_SECONDS = 30


@router.get("/public")
async def public_stats(db: DBSession):
    """
    Chiffres globaux, sans aucune donnée personnelle. Mis en cache 30 s :
    la page d'accueil peut être ouverte par beaucoup de monde sans charger
    la base de données.
    """

    now = time.monotonic()

    if _CACHE["data"] is not None and _CACHE["until"] > now:
        return _CACHE["data"]

    completed = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.status == "completed")
    )

    volume = await db.scalar(
        select(func.coalesce(func.sum(Transaction.channel_price), 0))
        .where(Transaction.status == "completed")
    )

    active = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.status.in_(ACTIVE_STATUSES))
    )

    channels = await db.scalar(
        select(func.count())
        .select_from(Listing)
        .join(Channel, Channel.id == Listing.channel_id)
        .where(
            Listing.status == "published",
            Listing.is_public.is_(True),
            Channel.is_active.is_(True),
        )
    )

    users = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.is_active.is_(True))
    )

    data = {
        "completed_sales": completed or 0,
        "available_channels": channels or 0,
        "active_transactions": active or 0,
        "members": users or 0,
        "volume": float(volume or 0),
        "currency": "XAF",
    }

    _CACHE["data"] = data
    _CACHE["until"] = now + _CACHE_SECONDS

    return data
