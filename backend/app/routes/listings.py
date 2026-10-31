# backend/app/routes/listings.py
#
# Réécriture : l'ancienne version utilisait un "pont sync -> async" et
# des colonnes qui n'existent plus dans les modèles (Channel.username,
# Channel.telegram_verified, Listing.validated_by_id, ...), donc chaque
# route plantait. Cette version est 100 % async et alignée sur les modèles.
#
# Cycle de vie d'une annonce :
#   pending_review --(admin)--> published  --(achat)--> reserved --> sold
#                 \--(admin)--> rejected
#   (cancelled possible par le vendeur tant qu'elle n'est pas réservée)

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, or_, select

from app.config import settings
from app.deps import CurrentUser, DBSession
from app.models.channel import Channel
from app.models.listing import Listing
from app.models.schemas import ListingCreate, ListingUpdate


router = APIRouter(
    prefix="/listings",
    tags=["Listings"],
)

ACTIVE_STATUSES = ("pending_review", "published", "reserved")


# ============================================================
# SÉRIALISATION PUBLIQUE
# ============================================================

def listing_to_dict(listing: Listing, channel: Channel | None) -> dict:
    """Aucune donnée d'identité vendeur / interne (ni owner_telegram_id)."""

    return {
        "id": listing.id,
        "channel_id": listing.channel_id,
        "title": listing.title,
        "category": listing.category,
        "price": float(listing.price),
        "currency": listing.currency,
        "description": listing.description,
        "status": listing.status,
        "is_public": listing.is_public,
        "published_at": (
            listing.published_at.isoformat()
            if listing.published_at
            else None
        ),
        "created_at": (
            listing.created_at.isoformat() if listing.created_at else None
        ),
        "updated_at": (
            listing.updated_at.isoformat() if listing.updated_at else None
        ),
        "channel": (
            {
                "id": channel.id,
                "title": channel.title,
                "telegram_username": channel.telegram_username,
                # alias conservés pour le frontend existant
                "username": channel.telegram_username,
                "description": channel.description,
                "photo_url": channel.photo_url,
                "subscriber_count": channel.subscriber_count,
                "subscribers_count": channel.subscriber_count,
                "verified": bool(
                    channel.verification_status == "approved"
                    and channel.bot_is_admin
                    and channel.owner_verified
                ),
                # champs lus par le frontend (badges de vérification)
                "telegram_verified": bool(
                    channel.verification_status == "approved"
                ),
                "bot_is_admin": bool(channel.bot_is_admin),
                "seller_is_admin": bool(channel.owner_verified),
                "is_active": channel.is_active,
            }
            if channel
            else None
        ),
    }


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


async def _get_own_listing(
    listing_id: int,
    user_id: int,
    db,
    *,
    lock: bool = False,
) -> Listing:
    query = select(Listing).where(Listing.id == listing_id)

    if lock:
        query = query.with_for_update()

    listing = (await db.execute(query)).scalar_one_or_none()

    # 404 (et non 403) : on ne révèle pas l'existence d'une annonce d'autrui.
    if listing is None or listing.seller_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    return listing


# ============================================================
# LISTE PUBLIQUE
# ============================================================

@router.get("")
async def get_listings(
    db: DBSession,
    search: str | None = None,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_subscribers: int | None = None,
    max_subscribers: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    conditions = [
        Listing.status == "published",
        Listing.is_public.is_(True),
        Channel.is_active.is_(True),
        Channel.verification_status == "approved",
    ]

    if search:
        value = _escape_like(search.strip().lower().replace("@", ""))

        if value:
            pattern = f"%{value}%"
            conditions.append(
                or_(
                    func.lower(Channel.title).like(pattern, escape="\\"),
                    func.lower(Channel.telegram_username).like(
                        pattern, escape="\\"
                    ),
                    func.lower(Listing.title).like(pattern, escape="\\"),
                )
            )

    if category:
        conditions.append(Listing.category == category)

    if min_price is not None:
        conditions.append(Listing.price >= min_price)

    if max_price is not None:
        conditions.append(Listing.price <= max_price)

    if min_subscribers is not None:
        conditions.append(Channel.subscriber_count >= min_subscribers)

    if max_subscribers is not None:
        conditions.append(Channel.subscriber_count <= max_subscribers)

    base = (
        select(Listing, Channel)
        .join(Channel, Listing.channel_id == Channel.id)
        .where(*conditions)
    )

    total = (
        await db.execute(
            select(func.count())
            .select_from(Listing)
            .join(Channel, Listing.channel_id == Channel.id)
            .where(*conditions)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(Listing.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return {
        "status": "success",
        "total": total,
        "limit": limit,
        "offset": offset,
        "listings": [listing_to_dict(l, c) for l, c in rows],
    }


# ============================================================
# MES ANNONCES (déclaré AVANT /{listing_id})
# ============================================================

@router.get("/mine/all")
async def get_my_listings(
    db: DBSession,
    current_user: CurrentUser,
):
    rows = (
        await db.execute(
            select(Listing, Channel)
            .join(Channel, Listing.channel_id == Channel.id)
            .where(Listing.seller_id == current_user.id)
            .order_by(Listing.created_at.desc())
        )
    ).all()

    return {
        "status": "success",
        "count": len(rows),
        "listings": [listing_to_dict(l, c) for l, c in rows],
    }


# ============================================================
# UNE ANNONCE (publique)
# ============================================================

@router.get("/{listing_id}")
async def get_listing(
    listing_id: int,
    db: DBSession,
):
    row = (
        await db.execute(
            select(Listing, Channel)
            .join(Channel, Listing.channel_id == Channel.id)
            .where(Listing.id == listing_id)
        )
    ).first()

    if row is None:
        raise HTTPException(404, "Annonce introuvable.")

    listing, channel = row

    if listing.status not in ("published", "reserved") or not listing.is_public:
        raise HTTPException(404, "Cette annonce n'est plus disponible.")

    return {
        "status": "success",
        "listing": listing_to_dict(listing, channel),
    }


# ============================================================
# CRÉER UNE ANNONCE
# ============================================================

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: ListingCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    # Verrou sur la chaîne : empêche deux annonces actives simultanées
    # créées par deux requêtes parallèles.
    channel = (
        await db.execute(
            select(Channel)
            .where(
                Channel.id == payload.channel_id,
                Channel.owner_id == current_user.id,
                Channel.is_active.is_(True),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            404,
            "Canal introuvable. Ajoutez d'abord le canal à votre compte.",
        )

    # Le vendeur crée canal + annonce d'un seul geste : le canal peut
    # donc être encore "submitted". L'admin l'approuvera en validant
    # l'annonce. Les vérifications Telegram, elles, sont obligatoires.
    if channel.verification_status not in ("submitted", "approved"):
        raise HTTPException(
            400,
            "Ce canal n'a pas été accepté. Soumettez-le à nouveau.",
        )

    if not channel.owner_verified:
        raise HTTPException(
            400,
            "Vous devez être propriétaire du canal pour le vendre.",
        )

    if not channel.bot_is_admin or not channel.bot_permissions_verified:
        raise HTTPException(
            400,
            "Le bot NexMarket doit être administrateur du canal "
            "avec les permissions requises.",
        )

    currency = payload.currency.strip().upper()

    if currency not in settings.get_supported_currencies():
        raise HTTPException(400, "Devise non supportée.")

    existing = (
        await db.execute(
            select(Listing.id).where(
                Listing.channel_id == channel.id,
                Listing.status.in_(ACTIVE_STATUSES),
            )
        )
    ).first()

    if existing:
        raise HTTPException(
            409,
            "Ce canal possède déjà une annonce active.",
        )

    listing = Listing(
        channel_id=channel.id,
        seller_id=current_user.id,
        title=(payload.title or channel.title or "Canal Telegram").strip(),
        category=payload.category,
        description=payload.description,
        price=payload.price,
        currency=currency,
        status="pending_review",
        is_public=False,
        # Le taux appliqué est figé sur l'annonce à sa création.
        platform_fee_rate=Decimal(str(settings.NEXMARKET_FEE_RATE)),
    )

    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    return {
        "status": "success",
        "message": (
            "Annonce créée et envoyée à l'administration pour validation."
        ),
        "listing": listing_to_dict(listing, channel),
    }


# ============================================================
# MODIFIER UNE ANNONCE
# ============================================================

@router.patch("/{listing_id}")
async def update_listing(
    listing_id: int,
    payload: ListingUpdate,
    db: DBSession,
    current_user: CurrentUser,
):
    listing = await _get_own_listing(
        listing_id, current_user.id, db, lock=True
    )

    if listing.status in ("reserved", "sold"):
        raise HTTPException(
            409,
            "Une annonce réservée ou vendue ne peut plus être modifiée.",
        )

    if listing.status == "cancelled":
        raise HTTPException(409, "Cette annonce est annulée.")

    data = payload.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(400, "Aucune modification fournie.")

    if "currency" in data and data["currency"] is not None:
        currency = data["currency"].strip().upper()

        if currency not in settings.get_supported_currencies():
            raise HTTPException(400, "Devise non supportée.")

        data["currency"] = currency

    for field in ("price", "currency", "title", "description", "category"):
        if field in data and data[field] is not None:
            setattr(listing, field, data[field])

    # Toute modification d'une annonce en ligne (ou refusée) repasse
    # par la validation admin.
    if listing.status in ("published", "approved", "rejected"):
        listing.status = "pending_review"
        listing.is_public = False
        listing.published_at = None
        listing.reviewed_by_admin_id = None
        listing.reviewed_at = None
        listing.rejection_reason = None

    await db.commit()
    await db.refresh(listing)

    channel = (
        await db.execute(
            select(Channel).where(Channel.id == listing.channel_id)
        )
    ).scalar_one_or_none()

    return {
        "status": "success",
        "listing": listing_to_dict(listing, channel),
    }


# ============================================================
# ANNULER UNE ANNONCE
# ============================================================

@router.post("/{listing_id}/cancel")
async def cancel_listing(
    listing_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    listing = await _get_own_listing(
        listing_id, current_user.id, db, lock=True
    )

    if listing.status == "reserved":
        raise HTTPException(
            409,
            "Une transaction est en cours sur cette annonce.",
        )

    if listing.status == "sold":
        raise HTTPException(409, "Cette annonce est déjà vendue.")

    listing.status = "cancelled"
    listing.is_public = False

    await db.commit()

    return {
        "status": "success",
        "message": "Annonce annulée.",
        "listing_id": listing.id,
    }
