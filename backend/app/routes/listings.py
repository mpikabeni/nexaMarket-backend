from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentAdmin, CurrentUser, DBSession
from app.models.channel import Channel
from app.models.listing import Listing
from app.models.schemas import (
    ListingCreate,
    ListingPublicResponse,
    ListingUpdate,
)


router = APIRouter(
    prefix="/listings",
    tags=["Listings"],
)


# ============================================================
# CREATE LISTING
# ============================================================

@router.post(
    "",
    response_model=ListingPublicResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing(
    payload: ListingCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Crée une annonce pour un canal appartenant
    à l'utilisateur connecté.

    L'annonce n'est PAS publiée immédiatement.
    """

    # --------------------------------------------------------
    # Vérifier le canal
    # --------------------------------------------------------

    result = await db.execute(
        select(Channel).where(
            Channel.id == payload.channel_id
        )
    )

    channel = result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=404,
            detail="Canal introuvable.",
        )

    if channel.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Vous ne pouvez créer une annonce "
                "que pour votre propre canal."
            ),
        )

    # --------------------------------------------------------
    # Vérifications Telegram
    # --------------------------------------------------------

    if not channel.owner_verified:
        raise HTTPException(
            status_code=400,
            detail="Le propriétaire du canal n'est pas vérifié.",
        )

    if not channel.bot_is_admin:
        raise HTTPException(
            status_code=400,
            detail="Le bot NexMarket doit être administrateur.",
        )

    if not channel.bot_permissions_verified:
        raise HTTPException(
            status_code=400,
            detail=(
                "Les permissions du bot NexMarket "
                "ne sont pas encore vérifiées."
            ),
        )

    # --------------------------------------------------------
    # Devise
    # --------------------------------------------------------

    currency = payload.currency.upper()

    if currency not in settings.get_supported_currencies():
        raise HTTPException(
            status_code=400,
            detail="Devise non supportée.",
        )

    # --------------------------------------------------------
    # Prix
    # --------------------------------------------------------

    price = Decimal(str(payload.price))

    if price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Le prix doit être supérieur à zéro.",
        )

    # --------------------------------------------------------
    # Création
    # --------------------------------------------------------

    listing = Listing(
        channel_id=channel.id,
        seller_id=current_user.id,
        price=price,
        currency=currency,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        status="draft",
        platform_fee_rate=Decimal(
            str(settings.NEXMARKET_FEE_RATE)
        ),
        is_public=False,
    )

    db.add(listing)

    await db.commit()
    await db.refresh(listing)

    return listing


# ============================================================
# MY LISTINGS
# ============================================================

@router.get(
    "/mine",
)
async def get_my_listings(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les annonces du vendeur connecté.
    """

    result = await db.execute(
        select(Listing)
        .where(
            Listing.seller_id == current_user.id
        )
        .order_by(
            Listing.created_at.desc()
        )
    )

    listings = result.scalars().all()

    return {
        "listings": [
            {
                "id": listing.id,
                "channel_id": listing.channel_id,
                "price": listing.price,
                "currency": listing.currency,
                "title": listing.title,
                "description": listing.description,
                "category": listing.category,
                "status": listing.status,
                "is_public": listing.is_public,
                "rejection_reason": listing.rejection_reason,
                "created_at": listing.created_at,
                "published_at": listing.published_at,
            }
            for listing in listings
        ]
    }


# ============================================================
# GET PUBLIC LISTINGS
# ============================================================

@router.get(
    "",
    response_model=list[ListingPublicResponse],
)
async def get_public_listings(
    db: DBSession,
    category: str | None = Query(
        default=None,
        max_length=100,
    ),
    currency: str | None = Query(
        default=None,
        max_length=10,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
):
    """
    Retourne uniquement les annonces publiées.

    Aucune donnée privée du vendeur n'est exposée.
    """

    query = (
        select(Listing)
        .where(
            Listing.status == "published",
            Listing.is_public.is_(True),
        )
    )

    if category:
        query = query.where(
            Listing.category == category
        )

    if currency:
        query = query.where(
            Listing.currency == currency.upper()
        )

    query = (
        query
        .order_by(
            Listing.published_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    return list(result.scalars().all())


# ============================================================
# GET LISTING
# ============================================================

@router.get(
    "/{listing_id}",
    response_model=ListingPublicResponse,
)
async def get_listing(
    listing_id: int,
    db: DBSession,
):
    """
    Retourne une annonce publique.
    """

    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.status == "published",
            Listing.is_public.is_(True),
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    return listing


# ============================================================
# UPDATE LISTING
# ============================================================

@router.patch(
    "/{listing_id}",
    response_model=ListingPublicResponse,
)
async def update_listing(
    listing_id: int,
    payload: ListingUpdate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Modifie une annonce appartenant au vendeur.

    Une annonce déjà publiée ne peut pas être modifiée
    directement : elle doit repasser par la modération.
    """

    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    if listing.seller_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Vous n'êtes pas le vendeur de cette annonce.",
        )

    if listing.status in {
        "reserved",
        "sold",
        "suspended",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cette annonce ne peut plus être modifiée "
                "dans son état actuel."
            ),
        )

    if payload.price is not None:
        listing.price = Decimal(
            str(payload.price)
        )

    if payload.currency is not None:
        currency = payload.currency.upper()

        if currency not in settings.get_supported_currencies():
            raise HTTPException(
                status_code=400,
                detail="Devise non supportée.",
            )

        listing.currency = currency

    if payload.title is not None:
        listing.title = payload.title

    if payload.description is not None:
        listing.description = payload.description

    if payload.category is not None:
        listing.category = payload.category

    # Toute modification d'une annonce doit être
    # recontrôlée avant publication.
    listing.status = "draft"
    listing.is_public = False
    listing.reviewed_by_admin_id = None
    listing.reviewed_at = None
    listing.rejection_reason = None
    listing.published_at = None

    await db.commit()
    await db.refresh(listing)

    return listing


# ============================================================
# SUBMIT FOR REVIEW
# ============================================================

@router.post(
    "/{listing_id}/submit",
    response_model=ListingPublicResponse,
)
async def submit_listing_for_review(
    listing_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Envoie l'annonce à l'équipe NexMarket pour modération.
    """

    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    if listing.seller_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Vous n'êtes pas le vendeur de cette annonce.",
        )

    if listing.status not in {
        "draft",
        "rejected",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cette annonce ne peut pas être envoyée "
                "en modération."
            ),
        )

    channel_result = await db.execute(
        select(Channel).where(
            Channel.id == listing.channel_id
        )
    )

    channel = channel_result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=404,
            detail="Canal associé introuvable.",
        )

    if not (
        channel.owner_verified
        and channel.bot_is_admin
        and channel.bot_permissions_verified
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Le canal doit être entièrement vérifié "
                "avant la modération de l'annonce."
            ),
        )

    listing.status = "pending_review"
    listing.is_public = False
    listing.rejection_reason = None

    await db.commit()
    await db.refresh(listing)

    return listing


# ============================================================
# ADMIN REVIEW
# ============================================================

@router.post(
    "/{listing_id}/moderate",
)
async def moderate_listing(
    listing_id: int,
    action: str,
    reason: str | None,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Validation ou rejet d'une annonce par NexMarket.

    Actions :
        approve
        reject
        suspend
    """

    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable.",
        )

    if action not in {
        "approve",
        "reject",
        "suspend",
    }:
        raise HTTPException(
            status_code=400,
            detail="Action de modération invalide.",
        )

    if action == "approve":
        listing.status = "published"
        listing.is_public = True
        listing.reviewed_by_admin_id = current_admin.id
        listing.reviewed_at = __import__(
            "datetime"
        ).datetime.utcnow()
        listing.published_at = __import__(
            "datetime"
        ).datetime.utcnow()
        listing.rejection_reason = None

    elif action == "reject":
        listing.status = "rejected"
        listing.is_public = False
        listing.reviewed_by_admin_id = current_admin.id
        listing.reviewed_at = __import__(
            "datetime"
        ).datetime.utcnow()
        listing.rejection_reason = reason

    else:
        listing.status = "suspended"
        listing.is_public = False
        listing.reviewed_by_admin_id = current_admin.id
        listing.reviewed_at = __import__(
            "datetime"
        ).datetime.utcnow()
        listing.rejection_reason = reason

    await db.commit()
    await db.refresh(listing)

    return {
        "status": "success",
        "listing_id": listing.id,
        "listing_status": listing.status,
        "is_public": listing.is_public,
    }
