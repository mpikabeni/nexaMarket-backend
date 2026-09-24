# backend/app/routes/listings.py

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import fastapi
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.channel import Channel
from app.models.listings import Listing
from app.models.user import User
from app.schemas import ListingCreate, ListingUpdate


router = fastapi.APIRouter(
    prefix="/listings",
    tags=["Listings"],
)


# ============================================================
# OUTIL DE SERIALISATION
# ============================================================

def listing_to_dict(listing: Listing) -> dict:
    channel = listing.channel

    return {
        "id": listing.id,
        "channel_id": listing.channel_id,
        "seller_id": listing.seller_id,

        "price": float(listing.price),
        "currency": listing.currency,

        "description": listing.description,

        "status": listing.status,

        "admin_note": listing.admin_note,

        "validated_by_id": listing.validated_by_id,
        "validated_at": (
            listing.validated_at.isoformat()
            if listing.validated_at
            else None
        ),

        "locked_price": (
            float(listing.locked_price)
            if listing.locked_price is not None
            else None
        ),

        "locked_at": (
            listing.locked_at.isoformat()
            if listing.locked_at
            else None
        ),

        "publish_fee": float(
            listing.publish_fee
        ),

        "publish_fee_paid": listing.publish_fee_paid,

        "created_at": (
            listing.created_at.isoformat()
            if listing.created_at
            else None
        ),

        "updated_at": (
            listing.updated_at.isoformat()
            if listing.updated_at
            else None
        ),

        "channel": (
            {
                "id": channel.id,
                "telegram_chat_id": channel.telegram_chat_id,
                "title": channel.title,
                "username": channel.username,
                "description": channel.description,
                "photo_url": channel.photo_url,
                "category": channel.category,
                "country": channel.country,
                "language": channel.language,
                "subscribers_count": channel.subscribers_count,
                "telegram_verified": channel.telegram_verified,
                "bot_is_admin": channel.bot_is_admin,
                "seller_is_admin": channel.seller_is_admin,
                "verification_note": channel.verification_note,
                "verified_at": (
                    channel.verified_at.isoformat()
                    if channel.verified_at
                    else None
                ),
                "owner_id": channel.owner_id,
                "is_active": channel.is_active,
            }
            if channel
            else None
        ),
    }


# ============================================================
# LISTINGS PUBLIÉES
# ============================================================

@router.get("")
def get_listings(
    search: str | None = None,
    category: str | None = None,
    country: str | None = None,
    language: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_subscribers: int | None = None,
    max_subscribers: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = fastapi.Depends(get_db),
):
    """
    Retourne les annonces disponibles.

    Cette route est publique côté marketplace.
    """

    if limit < 1:
        limit = 1

    if limit > 100:
        limit = 100

    if offset < 0:
        offset = 0

    query = (
        db.query(Listing)
        .join(
            Channel,
            Listing.channel_id == Channel.id,
        )
        .filter(
            Listing.status == "available",
            Channel.is_active.is_(True),
            Channel.telegram_verified.is_(True),
        )
    )

    # --------------------------------------------------------
    # RECHERCHE
    # --------------------------------------------------------

    if search:
        search_value = (
            search.strip()
            .lower()
            .replace("@", "")
        )

        if search_value:
            pattern = f"%{search_value}%"

            query = query.filter(
                fastapi.sqlalchemy.or_(
                    fastapi.sqlalchemy.func.lower(
                        Channel.title
                    ).like(pattern),

                    fastapi.sqlalchemy.func.lower(
                        Channel.username
                    ).like(pattern),

                    fastapi.sqlalchemy.func.lower(
                        Channel.description
                    ).like(pattern),
                )
            )

    # --------------------------------------------------------
    # FILTRES
    # --------------------------------------------------------

    if category:
        query = query.filter(
            Channel.category == category
        )

    if country:
        query = query.filter(
            Channel.country == country
        )

    if language:
        query = query.filter(
            Channel.language == language
        )

    if min_price is not None:
        query = query.filter(
            Listing.price >= min_price
        )

    if max_price is not None:
        query = query.filter(
            Listing.price <= max_price
        )

    if min_subscribers is not None:
        query = query.filter(
            Channel.subscribers_count
            >= min_subscribers
        )

    if max_subscribers is not None:
        query = query.filter(
            Channel.subscribers_count
            <= max_subscribers
        )

    total = query.count()

    listings = (
        query
        .order_by(
            Listing.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "status": "success",
        "total": total,
        "limit": limit,
        "offset": offset,
        "listings": [
            listing_to_dict(listing)
            for listing in listings
        ],
    }


# ============================================================
# UNE ANNONCE
# ============================================================

@router.get("/{listing_id}")
def get_listing(
    listing_id: int,
    db: Session = fastapi.Depends(get_db),
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
        )
        .first()
    )

    if not listing:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    if listing.status not in (
        "available",
        "reserved",
    ):
        raise fastapi.HTTPException(
            status_code=404,
            detail="Cette annonce n'est plus disponible.",
        )

    return {
        "status": "success",
        "listing": listing_to_dict(
            listing
        ),
    }


# ============================================================
# MES ANNONCES
# ============================================================

@router.get("/mine/all")
def get_my_listings(
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(
        get_current_user
    ),
):
    listings = (
        db.query(Listing)
        .filter(
            Listing.seller_id == current_user.id
        )
        .order_by(
            Listing.created_at.desc()
        )
        .all()
    )

    return {
        "status": "success",
        "count": len(listings),
        "listings": [
            listing_to_dict(listing)
            for listing in listings
        ],
    }


# ============================================================
# CRÉER UNE ANNONCE
# ============================================================

@router.post("")
def create_listing(
    payload: ListingCreate,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(
        get_current_user
    ),
):
    """
    Crée une annonce.

    L'annonce reste en "pending" jusqu'à validation
    par l'administration.
    """

    # --------------------------------------------------------
    # Recherche du canal
    # --------------------------------------------------------

    username = payload.username.strip()

    if username.startswith("@"):
        username = username[1:]

    channel = (
        db.query(Channel)
        .filter(
            Channel.username == username,
            Channel.owner_id == current_user.id,
            Channel.is_active.is_(True),
        )
        .first()
    )

    if not channel:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                "Canal introuvable. "
                "Ajoute d'abord le canal à ton compte."
            ),
        )

    # --------------------------------------------------------
    # Vérifications
    # --------------------------------------------------------

    if not channel.telegram_verified:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                "Le canal doit être vérifié "
                "avant de créer une annonce."
            ),
        )

    if not channel.bot_is_admin:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                "Le bot NexMarket doit être "
                "administrateur du canal."
            ),
        )

    if not channel.seller_is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail=(
                "Tu dois être administrateur "
                "du canal."
            ),
        )

    # --------------------------------------------------------
    # Vérifie qu'une annonce active n'existe pas
    # --------------------------------------------------------

    existing_listing = (
        db.query(Listing)
        .filter(
            Listing.channel_id == channel.id,
            Listing.seller_id == current_user.id,
            Listing.status.in_(
                [
                    "pending",
                    "available",
                    "reserved",
                ]
            ),
        )
        .first()
    )

    if existing_listing:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                "Ce canal possède déjà "
                "une annonce active."
            ),
        )

    # --------------------------------------------------------
    # Frais de publication
    # --------------------------------------------------------

    publish_fee = Decimal(
        str(
            settings.LISTING_PUBLISH_FEE
        )
    )

    publish_fee_paid = (
        publish_fee <= Decimal("0")
    )

    # --------------------------------------------------------
    # Création
    # --------------------------------------------------------

    listing = Listing(
        channel_id=channel.id,
        seller_id=current_user.id,

        price=payload.price,
        currency=current_user.currency,

        description=payload.description,

        status="pending",

        admin_note=None,
        validated_by_id=None,
        validated_at=None,

        locked_price=None,
        locked_at=None,

        publish_fee=publish_fee,
        publish_fee_paid=publish_fee_paid,
    )

    db.add(listing)
    db.commit()
    db.refresh(listing)

    return {
        "status": "success",
        "message": (
            "Annonce créée et envoyée "
            "à l'administration pour validation."
        ),
        "listing": listing_to_dict(
            listing
        ),
    }


# ============================================================
# MODIFIER UNE ANNONCE
# ============================================================

@router.patch("/{listing_id}")
def update_listing(
    listing_id: int,
    payload: ListingUpdate,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(
        get_current_user
    ),
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
            Listing.seller_id == current_user.id,
        )
        .first()
    )

    if not listing:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    # --------------------------------------------------------
    # Prix verrouillé
    # --------------------------------------------------------

    if listing.status == "reserved":
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                "Le prix est actuellement verrouillé "
                "par une transaction."
            ),
        )

    if listing.status == "sold":
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                "Cette annonce a déjà été vendue."
            ),
        )

    if listing.status in (
        "cancelled",
        "archived",
        "rejected",
    ):
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                "Cette annonce ne peut plus être modifiée."
            ),
        )

    # --------------------------------------------------------
    # Modification du prix
    # --------------------------------------------------------

    if payload.price is not None:
        listing.price = payload.price

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    if payload.description is not None:
        listing.description = (
            payload.description
        )

    # --------------------------------------------------------
    # Les catégories appartiennent au canal
    # --------------------------------------------------------

    channel = listing.channel

    if payload.category is not None:
        channel.category = payload.category

    if payload.country is not None:
        channel.country = payload.country

    if payload.language is not None:
        channel.language = payload.language

    # --------------------------------------------------------
    # Si une annonce disponible est modifiée,
    # elle repasse en validation.
    # --------------------------------------------------------

    if listing.status == "available":
        listing.status = "pending"
        listing.validated_by_id = None
        listing.validated_at = None
        listing.admin_note = (
            "Annonce modifiée : nouvelle validation requise."
        )

    db.commit()
    db.refresh(listing)

    return {
        "status": "success",
        "message": "Annonce mise à jour.",
        "listing": listing_to_dict(
            listing
        ),
    }


# ============================================================
# ANNULER UNE ANNONCE
# ============================================================

@router.post("/{listing_id}/cancel")
def cancel_listing(
    listing_id: int,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(
        get_current_user
    ),
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
            Listing.seller_id == current_user.id,
        )
        .first()
    )

    if not listing:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    if listing.status == "reserved":
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                "Impossible d'annuler cette annonce "
                "pendant une transaction active."
            ),
        )

    if listing.status == "sold":
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                "Cette annonce a déjà été vendue."
            ),
        )

    listing.status = "cancelled"

    db.commit()

    return {
        "status": "success",
        "message": "Annonce annulée.",
    }
