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

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, or_, select

from app.config import settings
from app.deps import CurrentUser, DBSession
from app.models.channel import Channel
from app.models.listing import Listing
from app.models.listing_proof import ListingProof
from app.models.review import Review
from app.models.transaction import Transaction
from app.models.user import User
from app.services import gram_rate, gram_service, ton
from app.services.media import channel_photo_url
from app.services.notification_service import admin_chat_ids, notify_admins_listing
from app.services.proofs import decode_previews, decode_proofs
from app.models.schemas import ListingCreate, ListingUpdate


router = APIRouter(
    prefix="/listings",
    tags=["Listings"],
)

ACTIVE_STATUSES = ("pending_review", "published", "reserved")


# ============================================================
# SÉRIALISATION PUBLIQUE
# ============================================================

def listing_to_dict(
    listing: Listing,
    channel: Channel | None,
    seller: dict | None = None,
) -> dict:
    """Aucune donnée d'identité vendeur / interne (ni owner_telegram_id)."""

    subscribers = (channel.subscriber_count or 0) if channel else 0
    price = float(listing.price)

    return {
        "id": listing.id,
        "channel_id": listing.channel_id,
        "title": listing.title,
        "category": listing.category,
        "price": price,
        "currency": listing.currency,
        # Annonce GRAM : prix en FCFA de référence (le prix en GRAM suit le marché).
        "price_xaf": (
            float(listing.price_xaf) if listing.price_xaf is not None else None
        ),
        # Repère de comparaison « boutique » : prix pour 1 000 abonnés.
        "price_per_1k": (
            round(price / subscribers * 1000)
            if subscribers > 0
            else None
        ),
        "seller": seller,
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
                # Canal PRIVÉ = pas de @username : pas de lien public.
                "is_private": not bool(channel.telegram_username),
                "channel_url": (
                    f"https://t.me/{channel.telegram_username}"
                    if channel.telegram_username
                    else None
                ),
                # alias conservés pour le frontend existant
                "username": channel.telegram_username,
                "description": channel.description,
                "photo_url": channel_photo_url(channel),
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


async def load_sellers(db, seller_ids: set[int]) -> dict[int, dict]:
    """Nom public, note moyenne et ventes terminées des vendeurs."""

    if not seller_ids:
        return {}

    users = (
        await db.execute(
            select(User.id, User.first_name, User.username, User.nexa_id)
            .where(User.id.in_(seller_ids))
        )
    ).all()

    ratings = {
        row[0]: (float(row[1]), row[2])
        for row in (
            await db.execute(
                select(
                    Review.reviewed_user_id,
                    func.avg(Review.rating),
                    func.count(),
                )
                .where(
                    Review.reviewed_user_id.in_(seller_ids),
                    Review.is_visible.is_(True),
                )
                .group_by(Review.reviewed_user_id)
            )
        ).all()
    }

    sales = dict(
        (
            await db.execute(
                select(Transaction.seller_id, func.count())
                .where(
                    Transaction.seller_id.in_(seller_ids),
                    Transaction.status == "completed",
                )
                .group_by(Transaction.seller_id)
            )
        ).all()
    )

    result = {}

    for user_id, first_name, username, nexa_id in users:
        average, count = ratings.get(user_id, (None, 0))

        result[user_id] = {
            "name": first_name or (f"@{username}" if username else "Vendeur"),
            "nexa_id": nexa_id,
            "rating": round(average, 1) if average is not None else None,
            "reviews": count,
            "sales": sales.get(user_id, 0),
        }

    return result


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
    sort: str = "recent",
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

    order = {
        "price_asc": Listing.price.asc(),
        "price_desc": Listing.price.desc(),
        "subs_desc": Channel.subscriber_count.desc(),
    }.get(sort, Listing.created_at.desc())

    rows = (
        await db.execute(
            base.order_by(order, Listing.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    sellers = await load_sellers(db, {l.seller_id for l, _ in rows})

    return {
        "status": "success",
        "total": total,
        "limit": limit,
        "offset": offset,
        "listings": [
            listing_to_dict(l, c, sellers.get(l.seller_id))
            for l, c in rows
        ],
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

    sellers = await load_sellers(db, {listing.seller_id})

    data = listing_to_dict(listing, channel, sellers.get(listing.seller_id))

    # Photos d'aperçu du canal (visibles par les acheteurs, surtout utiles
    # pour un canal privé que l'on ne peut pas ouvrir).
    data["preview_ids"] = list(
        (
            await db.execute(
                select(ListingProof.id)
                .where(
                    ListingProof.listing_id == listing.id,
                    ListingProof.kind == "preview",
                )
                .order_by(ListingProof.id)
            )
        ).scalars()
    )

    return {
        "status": "success",
        "listing": data,
    }


@router.get("/previews/{preview_id}")
async def get_preview_image(preview_id: int, db: DBSession):
    """Image d'aperçu d'une annonce PUBLIÉE (jamais les preuves de l'admin)."""

    row = (
        await db.execute(
            select(ListingProof, Listing)
            .join(Listing, Listing.id == ListingProof.listing_id)
            .where(ListingProof.id == preview_id, ListingProof.kind == "preview")
        )
    ).first()

    if row is None:
        raise HTTPException(404, "Image introuvable.")

    proof, listing = row

    if listing.status not in ("published", "reserved") or not listing.is_public:
        raise HTTPException(404, "Image introuvable.")

    return Response(
        content=proof.data,
        media_type=proof.content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


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

    if (channel.subscriber_count or 0) < settings.MIN_CHANNEL_SUBSCRIBERS:
        minimum = f"{settings.MIN_CHANNEL_SUBSCRIBERS:,}".replace(",", " ")
        raise HTTPException(
            400,
            f"Ton canal doit avoir au moins {minimum} abonnés "
            "pour être mis en vente.",
        )

    currency = payload.currency.strip().upper()
    gram_address = None
    listing_price = payload.price
    listing_price_xaf = None

    if currency == "GRAM":
        # Annonce payée en GRAM (TON) : adresse du vendeur + prix minimal.
        if not gram_service.enabled():
            raise HTTPException(400, "Le paiement en GRAM n'est pas disponible pour le moment.")
        if not ton.is_valid_address(payload.gram_address or ""):
            raise HTTPException(
                400,
                "Adresse GRAM invalide : recopiez-la depuis votre portefeuille "
                "(c'est là que vous recevrez le paiement).",
            )
        gram_address = payload.gram_address.strip()
        if payload.price_xaf is not None:
            # Prix fixé en FCFA : converti en GRAM au cours du marché.
            try:
                gram_price, _rate = await gram_rate.quote(payload.price_xaf)
            except gram_rate.GramRateUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            listing_price = gram_price
            listing_price_xaf = payload.price_xaf
        else:
            listing_price = payload.price
        if listing_price < Decimal("1"):
            raise HTTPException(
                400,
                "Le prix minimum est de 1 GRAM : augmentez le prix en FCFA.",
            )
    elif currency not in settings.get_supported_currencies():
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

    # Photos de preuve : facultatives (les aperçus du canal privé suffisent).
    try:
        proofs = decode_proofs(payload.proof_images)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Aperçu visible par les acheteurs : obligatoire pour un canal PRIVÉ
    # (pas de lien public pour le consulter).
    try:
        previews = decode_previews(
            payload.preview_images,
            required=not bool(channel.telegram_username),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    listing = Listing(
        channel_id=channel.id,
        seller_id=current_user.id,
        title=(payload.title or channel.title or "Canal Telegram").strip(),
        category=payload.category,
        description=payload.description,
        price=listing_price,
        price_xaf=listing_price_xaf,
        currency=currency,
        seller_gram_address=gram_address,
        status="pending_review",
        is_public=False,
        # Le taux appliqué est figé sur l'annonce à sa création.
        platform_fee_rate=Decimal(str(settings.NEXMARKET_FEE_RATE)),
    )

    db.add(listing)
    await db.flush()

    for content_type, data in proofs:
        db.add(
            ListingProof(
                listing_id=listing.id,
                kind="proof",
                content_type=content_type,
                data=data,
            )
        )

    for content_type, data in previews:
        db.add(
            ListingProof(
                listing_id=listing.id,
                kind="preview",
                content_type=content_type,
                data=data,
            )
        )

    await db.commit()
    await db.refresh(listing)

    # Prévenir les administrateurs, photos de preuve jointes.
    notify_admins_listing(
        await admin_chat_ids(db),
        (
            "🆕 Nouvelle annonce à valider\n\n"
            f"Canal : {listing.title}\n"
            + (
                f"Lien : https://t.me/{channel.telegram_username}\n"
                if channel.telegram_username
                else f"Canal PRIVÉ (ID {channel.telegram_channel_id})\n"
            )
            + f"Abonnés : {channel.subscriber_count or 0}\n"
            f"Prix : {listing.price} {listing.currency}\n"
            f"Vendeur : {current_user.first_name or current_user.username or current_user.nexa_id}"
            f" ({current_user.nexa_id})"
        ),
        [data for _, data in (proofs or previews)],
    )

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

        # Le moyen de paiement (XAF ou GRAM) ne change pas après la création :
        # une annonce GRAM porte l'adresse du vendeur, pas une annonce XAF.
        if (currency == "GRAM") != (listing.currency == "GRAM"):
            raise HTTPException(
                400,
                "Le moyen de paiement ne peut pas être changé : créez une nouvelle annonce.",
            )

        if currency != "GRAM" and currency not in settings.get_supported_currencies():
            raise HTTPException(400, "Devise non supportée.")

        data["currency"] = currency

    if listing.currency == "GRAM" and listing.price_xaf is not None:
        # Annonce à prix en FCFA : on modifie le prix en FCFA, le prix en
        # GRAM en est déduit au cours du marché.
        if data.get("price") is not None and data.get("price_xaf") is None:
            raise HTTPException(400, "Indiquez le nouveau prix en FCFA.")
        data.pop("price", None)
        if data.get("price_xaf") is not None:
            try:
                new_gram, _rate = await gram_rate.quote(data["price_xaf"])
            except gram_rate.GramRateUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            if new_gram < Decimal("1"):
                raise HTTPException(
                    400,
                    "Le prix minimum est de 1 GRAM : augmentez le prix en FCFA.",
                )
            listing.price_xaf = data["price_xaf"]
            data["price"] = new_gram
    else:
        data.pop("price_xaf", None)
        if (
            listing.currency == "GRAM"
            and data.get("price") is not None
            and Decimal(str(data["price"])) < Decimal("1")
        ):
            raise HTTPException(400, "Le prix minimum en GRAM est de 1 GRAM.")

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
