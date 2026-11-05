import asyncio
from datetime import datetime, timezone
import hmac
import time

from fastapi import (
    Response,
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.auth import (
    create_access_token,
    validate_telegram_init_data,
)
from app.config import settings
from app.deps import CurrentAdmin, DBSession
from app.models.channel import Channel
from app.models.listing import Listing
from app.services.notification_service import notify_user_id
from app.models.message import Message
from app.models.platform import PlatformWallet
from app.models.listing_proof import ListingProof
from app.models.schemas import (
    AnnouncementRequest,
    RejectRequest,
    WithdrawalResolveRequest,
)
from app.services.telegram_service import get_telegram_service
from app.models.withdrawal import Withdrawal
from app.services.payout_settlement import complete_withdrawal, fail_withdrawal
from app.models.report import Report
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


# ============================================================
# ADMIN LOGIN
# ============================================================

class AdminLoginRequest(BaseModel):
    code: str


# Limite d'essais : 5 échecs / 10 min par adresse IP (mémoire du processus ;
# le service tourne avec un seul worker). Évite de deviner le code admin.
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 600
_login_failures: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "inconnu"


def _login_check(ip: str) -> None:
    now = time.monotonic()
    recent = [
        t for t in _login_failures.get(ip, [])
        if now - t < _LOGIN_WINDOW_SECONDS
    ]
    if recent:
        _login_failures[ip] = recent
    else:
        _login_failures.pop(ip, None)

    if len(recent) >= _LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessaie dans quelques minutes.",
        )


def _login_failed(ip: str) -> None:
    _login_failures.setdefault(ip, []).append(time.monotonic())
    if len(_login_failures) > 1000:
        _login_failures.clear()


@router.post("/login")
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    db: DBSession,
    telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    """
    Connexion administrateur NexMarket.

    Le frontend envoie :
        {
            "code": "CODE_ADMIN"
        }

    ainsi que le header :
        X-Telegram-Init-Data

    Le compte Telegram doit correspondre à
    ADMIN_TELEGRAM_ID dans Render.
    """

    # --------------------------------------------------------
    # Vérification de la configuration
    # --------------------------------------------------------

    if not settings.ADMIN_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Le code administrateur n'est pas configuré "
                "(variable ADMIN_CODE sur Render)."
            ),
        )

    # --------------------------------------------------------
    # Vérification du code administrateur
    # --------------------------------------------------------

    ip = _client_ip(request)
    _login_check(ip)

    if not payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le code administrateur est obligatoire.",
        )

    if not hmac.compare_digest(
        str(payload.code),
        str(settings.ADMIN_CODE),
    ):
        _login_failed(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Code administrateur incorrect.",
        )

    # --------------------------------------------------------
    # Vérification Telegram
    # --------------------------------------------------------

    if not telegram_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Les données Telegram sont absentes. "
                "Ouvrez l'administration depuis la Mini App."
            ),
        )

    try:
        telegram_data = validate_telegram_init_data(
            telegram_init_data
        )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Les données Telegram sont invalides "
                "ou expirées."
            ),
        )

    # --------------------------------------------------------
    # Récupération Telegram ID
    # --------------------------------------------------------

    try:
        telegram_id = int(
            telegram_data["telegram_id"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Impossible de récupérer "
                "l'identifiant Telegram."
            ),
        )

    # --------------------------------------------------------
    # Recherche du compte utilisateur
    # --------------------------------------------------------

    result = await db.execute(
        select(User).where(
            User.telegram_id == telegram_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Votre compte NexMarket est introuvable. "
                "Utilisez d'abord /start sur le bot."
            ),
        )

    # --------------------------------------------------------
    # Est-ce bien un administrateur ?
    # --------------------------------------------------------
    # MÊME règle que le bot (is_admin_user) : l'ID Telegram défini dans
    # ADMIN_TELEGRAM_ID, OU un compte déjà marqué administrateur.
    # Avant, la Mini App n'acceptait que ADMIN_TELEGRAM_ID : le bot te
    # reconnaissait admin mais la Mini App répondait « Accès refusé ».
    configured_admin = bool(settings.ADMIN_TELEGRAM_ID) and (
        telegram_id == int(settings.ADMIN_TELEGRAM_ID)
    )

    if not (configured_admin or user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Ce compte Telegram n'est pas administrateur de NexMarket."
                + (
                    ""
                    if settings.ADMIN_TELEGRAM_ID
                    else " Aucun ADMIN_TELEGRAM_ID n'est configuré "
                    "sur le serveur."
                )
            ),
        )

    # --------------------------------------------------------
    # Vérification compte actif
    # --------------------------------------------------------

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre compte NexMarket est désactivé.",
        )

    # --------------------------------------------------------
    # Promotion automatique en administrateur
    # --------------------------------------------------------

    if not user.is_admin:
        user.is_admin = True

        await db.commit()
        await db.refresh(user)

    # --------------------------------------------------------
    # Création du JWT
    # --------------------------------------------------------

    access_token = create_access_token(
        user.id
    )

    # --------------------------------------------------------
    # Réponse frontend
    # --------------------------------------------------------

    return {
        "token": access_token,
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in_minutes": (
            settings.JWT_EXPIRE_MINUTES
        ),
        "admin": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "nexa_id": user.nexa_id,
            "is_admin": user.is_admin,
        },
    }


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/dashboard")
async def admin_dashboard(
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Statistiques générales de NexMarket.
    """

    users_count = await db.scalar(
        select(func.count(User.id))
    )

    channels_count = await db.scalar(
        select(func.count(Channel.id))
    )

    pending_channels = await db.scalar(
        select(func.count(Channel.id)).where(
            Channel.verification_status.in_(
                [
                    "pending",
                    "submitted",
                ]
            )
        )
    )

    listings_count = await db.scalar(
        select(func.count(Listing.id))
    )

    pending_listings = await db.scalar(
        select(func.count(Listing.id)).where(
            Listing.status == "pending_review"
        )
    )

    transactions_count = await db.scalar(
        select(func.count(Transaction.id))
    )

    active_transactions = await db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.status.in_(
                [
                    "pending_payment",
                    "waiting_admin",
                    "transfer_started",
                    "protection_period",
                    "disputed",
                ]
            )
        )
    )

    pending_reports = await db.scalar(
        select(func.count(Report.id)).where(
            Report.status.in_(
                [
                    "pending",
                    "investigating",
                ]
            )
        )
    )

    platform_balance = await db.scalar(
        select(func.coalesce(func.sum(PlatformWallet.available_balance), 0))
    )

    return {
        "platform_wallet": {
            "balance": platform_balance or 0,
            "currency": "XAF",
        },
        "users": users_count or 0,
        "channels": channels_count or 0,
        "pending_channels": pending_channels or 0,
        "listings": listings_count or 0,
        "pending_listings": pending_listings or 0,
        "transactions": transactions_count or 0,
        "active_transactions": active_transactions or 0,
        "pending_reports": pending_reports or 0,
    }


# ============================================================
# USERS
# ============================================================

@router.get("/users")
async def admin_users(
    current_admin: CurrentAdmin,
    db: DBSession,
    active_only: bool = False,
):
    """
    Liste les utilisateurs pour l'administration.
    """

    query = select(User).order_by(
        User.created_at.desc()
    )

    if active_only:
        query = query.where(
            User.is_active.is_(True)
        )

    result = await db.execute(query)

    users = result.scalars().all()

    return {
        "users": [
            {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "nexa_id": user.nexa_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "is_admin": user.is_admin,
                "language": user.language,
                "preferred_currency": (
                    user.preferred_currency
                ),
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            }
            for user in users
        ],
        "count": len(users),
    }


# ============================================================
# ACTIVATE / DEACTIVATE USER
# ============================================================

@router.patch("/users/{user_id}/status")
async def change_user_status(
    user_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
    active: bool,
):
    """
    Active ou désactive un compte utilisateur.
    """

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    if user.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Un administrateur ne peut pas "
                "désactiver son propre compte."
            ),
        )

    user.is_active = active

    await db.commit()
    await db.refresh(user)

    return {
        "status": "success",
        "user_id": user.id,
        "is_active": user.is_active,
    }


# ============================================================
# CHANNELS - PENDING
# ============================================================

@router.get("/channels/pending")
async def pending_channels(
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Liste les chaînes nécessitant une vérification.
    """

    result = await db.execute(
        select(Channel)
        .where(
            Channel.verification_status.in_(
                [
                    "pending",
                    "submitted",
                ]
            )
        )
        .order_by(
            Channel.created_at.asc()
        )
    )

    channels = result.scalars().all()

    return {
        "channels": [
            {
                "id": channel.id,
                "telegram_username": (
                    channel.telegram_username
                ),
                "title": channel.title,
                "description": channel.description,
                "subscriber_count": (
                    channel.subscriber_count
                ),
                "bot_is_admin": (
                    channel.bot_is_admin
                ),
                "bot_permissions_verified": (
                    channel.bot_permissions_verified
                ),
                "owner_verified": (
                    channel.owner_verified
                ),
                "verification_status": (
                    channel.verification_status
                ),
                "created_at": channel.created_at,
            }
            for channel in channels
        ],
        "count": len(channels),
    }


# ============================================================
# APPROVE CHANNEL
# ============================================================

@router.post("/channels/{channel_id}/approve")
async def approve_channel(
    channel_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Approuve une chaîne après vérification.
    """

    result = await db.execute(
        select(Channel).where(
            Channel.id == channel_id
        )
    )

    channel = result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chaîne introuvable.",
        )

    if not channel.bot_is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le bot NexMarket n'est pas "
                "administrateur de la chaîne."
            ),
        )

    if not channel.bot_permissions_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Les permissions du bot "
                "n'ont pas été vérifiées."
            ),
        )

    if not channel.owner_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le propriétaire Telegram "
                "n'a pas été vérifié."
            ),
        )

    now = datetime.now(timezone.utc)

    channel.verification_status = "approved"
    channel.verified_at = now
    channel.verified_by_admin_id = current_admin.id
    channel.rejection_reason = None
    channel.is_active = True

    await db.commit()
    await db.refresh(channel)

    return {
        "status": "success",
        "channel_id": channel.id,
        "verification_status": (
            channel.verification_status
        ),
        "verified_at": channel.verified_at,
        "verified_by_admin_id": (
            channel.verified_by_admin_id
        ),
    }


# ============================================================
# REJECT CHANNEL
# ============================================================

@router.post("/channels/{channel_id}/reject")
async def reject_channel(
    channel_id: int,
    payload: RejectRequest,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Rejette une chaîne.
    """

    cleaned_reason = payload.reason.strip()

    if not cleaned_reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le motif du rejet est obligatoire.",
        )

    result = await db.execute(
        select(Channel).where(
            Channel.id == channel_id
        )
    )

    channel = result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chaîne introuvable.",
        )

    channel.verification_status = "rejected"
    channel.verified_by_admin_id = current_admin.id
    channel.rejection_reason = cleaned_reason
    channel.is_listed = False

    await db.commit()
    await db.refresh(channel)

    return {
        "status": "success",
        "channel_id": channel.id,
        "verification_status": (
            channel.verification_status
        ),
        "rejection_reason": (
            channel.rejection_reason
        ),
    }


# ============================================================
# LISTINGS - PENDING
# ============================================================

@router.get("/listings/pending")
async def pending_listings(
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Liste les annonces en attente de modération, avec le canal, le vendeur
    et le nombre de photos de preuve (pour décider sans ouvrir chaque fiche).
    """

    rows = (
        await db.execute(
            select(Listing, Channel, User)
            .join(Channel, Channel.id == Listing.channel_id)
            .join(User, User.id == Listing.seller_id)
            .where(Listing.status == "pending_review")
            .order_by(Listing.created_at.asc())
        )
    ).all()

    proof_counts = dict(
        (
            await db.execute(
                select(ListingProof.listing_id, func.count())
                .where(
                    ListingProof.listing_id.in_([row[0].id for row in rows])
                )
                .group_by(ListingProof.listing_id)
            )
        ).all()
    ) if rows else {}

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
                "platform_fee_rate": listing.platform_fee_rate,
                "created_at": listing.created_at,
                "proofs_count": proof_counts.get(listing.id, 0),
                "channel": {
                    "title": channel.title,
                    "telegram_username": channel.telegram_username,
                    "is_private": not bool(channel.telegram_username),
                    "subscriber_count": channel.subscriber_count,
                },
                "seller": {
                    "id": seller.id,
                    "name": (
                        " ".join(
                            part
                            for part in (seller.first_name, seller.last_name)
                            if part
                        )
                        or seller.username
                        or seller.nexa_id
                    ),
                    "nexa_id": seller.nexa_id,
                },
            }
            for listing, channel, seller in rows
        ],
        "count": len(rows),
    }


# ============================================================
# APPROVE LISTING
# ============================================================

@router.post("/listings/{listing_id}/approve")
async def approve_listing(
    listing_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
    without_proofs: bool = False,
):
    """
    Approuve et publie une annonce.
    """

    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    # Les photos de preuve (envoyées par le vendeur) doivent exister.
    proofs_count = await db.scalar(
        select(func.count())
        .select_from(ListingProof)
        .where(ListingProof.listing_id == listing_id)
    )

    if not proofs_count and not without_proofs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Aucune photo de preuve n'a été fournie pour cette annonce. "
                "Demandez-les au vendeur, ou approuvez quand même en "
                "confirmant."
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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chaîne associée introuvable.",
        )

    # Le vendeur a soumis canal + annonce ensemble : valider l'annonce
    # approuve aussi le canal (s'il n'a pas été rejeté).
    if channel.verification_status not in ("submitted", "approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La chaîne associée n'est pas acceptable.",
        )

    if not channel.owner_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le propriétaire de la chaîne "
                "n'est pas vérifié."
            ),
        )

    if not channel.bot_permissions_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Les permissions du bot "
                "ne sont pas vérifiées."
            ),
        )

    now = datetime.now(timezone.utc)

    listing.status = "published"
    listing.is_public = True
    listing.reviewed_by_admin_id = current_admin.id
    listing.reviewed_at = now
    listing.rejection_reason = None
    listing.published_at = now

    channel.is_listed = True

    if channel.verification_status != "approved":
        channel.verification_status = "approved"
        channel.verified_at = now
        channel.verified_by_admin_id = current_admin.id
        channel.rejection_reason = None
        channel.is_active = True

    await db.commit()
    await db.refresh(listing)

    await notify_user_id(
        db,
        listing.seller_id,
        "✅ Votre annonce a été approuvée et est maintenant visible "
        "sur NexMarket.",
    )

    return {
        "status": "success",
        "listing_id": listing.id,
        "listing_status": listing.status,
        "is_public": listing.is_public,
        "published_at": listing.published_at,
    }


# ============================================================
# REJECT LISTING
# ============================================================

@router.post("/listings/{listing_id}/reject")
async def reject_listing(
    listing_id: int,
    payload: RejectRequest,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Rejette une annonce.
    """

    cleaned_reason = payload.reason.strip()

    if not cleaned_reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le motif du rejet est obligatoire.",
        )

    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    listing.status = "rejected"
    listing.is_public = False
    listing.reviewed_by_admin_id = current_admin.id
    listing.reviewed_at = (
        datetime.now(timezone.utc)
    )
    listing.rejection_reason = cleaned_reason

    await db.commit()
    await db.refresh(listing)

    await notify_user_id(
        db,
        listing.seller_id,
        "❌ Votre annonce n'a pas été approuvée.\n\nMotif : "
        + cleaned_reason,
    )

    return {
        "status": "success",
        "listing_id": listing.id,
        "listing_status": listing.status,
        "is_public": listing.is_public,
        "rejection_reason": (
            listing.rejection_reason
        ),
    }


# ============================================================
# TRANSACTIONS - ACTIVE
# ============================================================

@router.get("/transactions")
async def admin_transactions(
    current_admin: CurrentAdmin,
    db: DBSession,
    transaction_status: str | None = None,
):
    """
    Liste les transactions pour l'administration.
    """

    query = select(Transaction)

    if transaction_status:
        query = query.where(
            Transaction.status == transaction_status
        )

    query = query.order_by(
        Transaction.created_at.desc()
    )

    result = await db.execute(query)

    transactions = result.scalars().all()

    return {
        "transactions": [
            {
                "id": transaction.id,
                "reference": transaction.reference,
                "listing_id": transaction.listing_id,
                "buyer_id": transaction.buyer_id,
                "seller_id": transaction.seller_id,
                "assigned_admin_id": (
                    transaction.assigned_admin_id
                ),
                "channel_price": (
                    transaction.channel_price
                ),
                "platform_fee": (
                    transaction.platform_fee
                ),
                "provider_fee": (
                    transaction.provider_fee
                ),
                "total_buyer_amount": (
                    transaction.total_buyer_amount
                ),
                "seller_amount": (
                    transaction.seller_amount
                ),
                "currency": transaction.currency,
                "status": transaction.status,
                "payment_provider": (
                    transaction.payment_provider
                ),
                "payment_status": (
                    transaction.payment_status
                ),
                "escrow_held": (
                    transaction.escrow_held
                ),
                "protection_ends_at": (
                    transaction.protection_ends_at
                ),
                "disputed_at": (
                    transaction.disputed_at
                ),
                "created_at": transaction.created_at,
            }
            for transaction in transactions
        ],
        "count": len(transactions),
    }


# ============================================================
# ASSIGN TRANSACTION
# ============================================================

@router.post(
    "/transactions/{transaction_id}/assign"
)
async def assign_transaction(
    transaction_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Assigne une transaction à l'admin connecté.
    """

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    transaction.assigned_admin_id = (
        current_admin.id
    )

    await db.commit()
    await db.refresh(transaction)

    return {
        "status": "success",
        "transaction_id": transaction.id,
        "assigned_admin_id": (
            transaction.assigned_admin_id
        ),
    }


# ============================================================
# REPORTS
# ============================================================

@router.get("/reports")
async def admin_reports(
    current_admin: CurrentAdmin,
    db: DBSession,
    report_status: str | None = None,
):
    """
    Liste les signalements.
    """

    query = select(Report)

    if report_status:
        query = query.where(
            Report.status == report_status
        )

    query = query.order_by(
        Report.created_at.desc()
    )

    result = await db.execute(query)

    reports = result.scalars().all()

    return {
        "reports": [
            {
                "id": report.id,
                "transaction_id": (
                    report.transaction_id
                ),
                "reporter_id": (
                    report.reporter_id
                ),
                "report_type": (
                    report.report_type
                ),
                "reason": report.reason,
                "status": report.status,
                "assigned_admin_id": (
                    report.assigned_admin_id
                ),
                "admin_resolution": (
                    report.admin_resolution
                ),
                "resolved_at": report.resolved_at,
                "created_at": report.created_at,
            }
            for report in reports
        ],
        "count": len(reports),
    }


# ============================================================
# WALLET / PLATFORM OVERVIEW
# ============================================================

@router.get("/wallets")
async def admin_wallets(
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Vue des soldes des wallets utilisateurs.

    Aucun numéro JessiKaPay privé n'est retourné.
    """

    result = await db.execute(
        select(Wallet)
        .order_by(
            Wallet.created_at.desc()
        )
    )

    wallets = result.scalars().all()

    return {
        "wallets": [
            {
                "id": wallet.id,
                "user_id": wallet.user_id,
                "available_balance": (
                    wallet.available_balance
                ),
                "blocked_balance": (
                    wallet.blocked_balance
                ),
                "total_revenue": (
                    wallet.total_revenue
                ),
                "currency": wallet.currency,
                "created_at": wallet.created_at,
                "updated_at": wallet.updated_at,
            }
            for wallet in wallets
        ],
        "count": len(wallets),
    }


# ============================================================
# ADMIN : SESSION
# ============================================================

@router.get("/me")
async def admin_me(current_admin: CurrentAdmin):
    return {
        "id": current_admin.id,
        "telegram_id": current_admin.telegram_id,
        "username": current_admin.username,
        "is_admin": True,
    }


# ============================================================
# ALL CHANNELS
# ============================================================

@router.get("/channels")
async def list_all_channels(
    current_admin: CurrentAdmin,
    db: DBSession,
    limit: int = 100,
):
    limit = max(1, min(limit, 200))

    channels = (
        await db.execute(
            select(Channel)
            .order_by(Channel.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "channels": [
            {
                "id": c.id,
                "telegram_username": c.telegram_username,
                "title": c.title,
                "subscriber_count": c.subscriber_count,
                "bot_is_admin": c.bot_is_admin,
                "owner_verified": c.owner_verified,
                "verification_status": c.verification_status,
                "is_active": c.is_active,
                "is_private": not bool(c.telegram_username),
                "telegram_channel_id": c.telegram_channel_id,
                "is_listed": c.is_listed,
                "owner_id": c.owner_id,
                "created_at": c.created_at,
            }
            for c in channels
        ]
    }


# ============================================================
# ONE LISTING (détail)
# ============================================================

@router.get("/listings/{listing_id}")
async def get_listing_detail(
    listing_id: int,
    current_admin: CurrentAdmin,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    listing, channel = row

    proof_ids = (
        await db.execute(
            select(ListingProof.id)
            .where(ListingProof.listing_id == listing_id)
            .order_by(ListingProof.id)
        )
    ).scalars().all()

    return {
        "id": listing.id,
        "title": listing.title,
        "description": listing.description,
        "category": listing.category,
        "price": listing.price,
        "currency": listing.currency,
        "status": listing.status,
        "is_public": listing.is_public,
        "rejection_reason": listing.rejection_reason,
        "seller_id": listing.seller_id,
        "created_at": listing.created_at,
        "proofs": [{"id": proof_id} for proof_id in proof_ids],
        "channel": {
            "id": channel.id,
            "title": channel.title,
            "telegram_username": channel.telegram_username,
            "subscriber_count": channel.subscriber_count,
            "bot_is_admin": channel.bot_is_admin,
            "bot_permissions_verified": channel.bot_permissions_verified,
            "owner_verified": channel.owner_verified,
            "verification_status": channel.verification_status,
        },
    }


# ============================================================
# MESSAGES (supervision des discussions de transaction)
# ============================================================

@router.get("/messages")
async def list_recent_messages(
    current_admin: CurrentAdmin,
    db: DBSession,
    limit: int = 100,
):
    limit = max(1, min(limit, 200))

    messages = (
        await db.execute(
            select(Message)
            .where(Message.is_deleted.is_(False))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "messages": [
            {
                "id": m.id,
                "transaction_id": m.transaction_id,
                "sender_id": m.sender_id,
                "sender_role": m.sender_role,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in messages
        ]
    }


# ============================================================
# PLATFORM WALLET (commissions)
# ============================================================

@router.get("/platform-wallet")
async def platform_wallet(
    current_admin: CurrentAdmin,
    db: DBSession,
):
    wallets = (
        await db.execute(select(PlatformWallet))
    ).scalars().all()

    return {
        "wallets": [
            {
                "currency": w.currency,
                "available_balance": w.available_balance,
                "total_revenue": w.total_revenue,
                "total_fees_collected": w.total_fees_collected,
            }
            for w in wallets
        ]
    }


# ============================================================
# RETRAITS AU STATUT INCONNU (pas de webhook)
# ============================================================

@router.get("/withdrawals")
async def list_withdrawals(
    current_admin: CurrentAdmin,
    db: DBSession,
    status_filter: str = "processing",
    limit: int = 100,
):
    """Retraits à vérifier (par défaut : « processing »)."""

    limit = max(1, min(limit, 200))

    rows = (
        await db.execute(
            select(Withdrawal)
            .where(Withdrawal.status == status_filter)
            .order_by(Withdrawal.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "withdrawals": [
            {
                "id": w.id,
                "reference": w.reference,
                "user_id": w.user_id,
                "amount": w.amount,
                "currency": w.currency,
                "jp_number": w.jessikapay_jp_number,
                "status": w.status,
                "failure_reason": w.failure_reason,
                "created_at": w.created_at,
            }
            for w in rows
        ]
    }


@router.post("/withdrawals/{withdrawal_id}/resolve")
async def resolve_withdrawal(
    withdrawal_id: int,
    payload: WithdrawalResolveRequest,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Tranche un retrait dont l'issue est inconnue, APRÈS avoir vérifié
    dans JessiKaPay si le versement a bien été fait :
      - complete : le versement a eu lieu -> les fonds bloqués sont consommés ;
      - fail     : il n'a pas eu lieu     -> les fonds sont rendus à l'utilisateur.
    """

    withdrawal = (
        await db.execute(
            select(Withdrawal)
            .where(Withdrawal.id == withdrawal_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if withdrawal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retrait introuvable.",
        )

    if withdrawal.status not in ("processing", "pending"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ce retrait est déjà « {withdrawal.status} ».",
        )

    withdrawal.reviewed_by_admin_id = current_admin.id
    withdrawal.admin_note = payload.note

    if payload.action == "complete":
        await complete_withdrawal(db, withdrawal)
    else:
        await fail_withdrawal(
            db,
            withdrawal,
            payload.note or "Retrait non effectué (décision admin).",
        )

    return {"id": withdrawal.id, "status": withdrawal.status}


# ============================================================
# PHOTOS DE PREUVE (consultation par l'administrateur)
# ============================================================

@router.get("/proofs/{proof_id}")
async def get_proof_image(
    proof_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    proof = (
        await db.execute(
            select(ListingProof).where(ListingProof.id == proof_id)
        )
    ).scalar_one_or_none()

    if proof is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo introuvable.",
        )

    return Response(
        content=proof.data,
        media_type=proof.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ============================================================
# SUPPRIMER UN CANAL
# ============================================================

ACTIVE_TRANSACTION_STATUSES = (
    "pending_payment",
    "waiting_admin",
    "transfer_started",
    "protection_period",
    "disputed",
)


@router.delete("/channels/{channel_id}")
async def remove_channel(
    channel_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Retire définitivement un canal de NexMarket : ses annonces sont
    annulées, il n'est plus visible et ne peut plus être remis en vente.
    L'historique des transactions terminées est conservé.
    """

    channel = (
        await db.execute(
            select(Channel)
            .where(Channel.id == channel_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal introuvable.",
        )

    active = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Listing, Listing.id == Transaction.listing_id)
        .where(
            Listing.channel_id == channel.id,
            Transaction.status.in_(ACTIVE_TRANSACTION_STATUSES),
        )
    )

    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Des transactions sont en cours sur ce canal : "
                "résolvez-les avant de le supprimer."
            ),
        )

    listings = (
        await db.execute(
            select(Listing).where(Listing.channel_id == channel.id)
        )
    ).scalars().all()

    cancelled = 0

    for listing in listings:
        if listing.status not in ("sold", "cancelled"):
            listing.status = "cancelled"
            cancelled += 1

        listing.is_public = False

    channel.is_active = False
    channel.is_listed = False
    channel.verification_status = "removed"

    title = channel.title
    owner_id = channel.owner_id

    await db.commit()

    await notify_user_id(
        db,
        owner_id,
        f"⛔ Votre canal « {title} » a été retiré de NexMarket par "
        "l'administration.",
    )

    return {
        "status": "success",
        "channel_id": channel_id,
        "listings_cancelled": cancelled,
    }


# ============================================================
# RETIRER UN UTILISATEUR DE LA MARKETPLACE
# ============================================================

@router.post("/users/{user_id}/remove")
async def remove_user(
    user_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Bloque le compte ET retire ses annonces et ses canaux de la
    marketplace. Les comptes ne sont jamais effacés de la base : l'historique
    financier (dépôts, retraits, transactions) doit rester traçable.
    """

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    if user.id == current_admin.id or user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un administrateur ne peut pas être retiré.",
        )

    active = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            or_(
                Transaction.buyer_id == user.id,
                Transaction.seller_id == user.id,
            ),
            Transaction.status.in_(ACTIVE_TRANSACTION_STATUSES),
        )
    )

    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cet utilisateur a des transactions en cours : "
                "résolvez-les d'abord."
            ),
        )

    listings = (
        await db.execute(
            select(Listing).where(
                Listing.seller_id == user.id,
                Listing.status.notin_(("sold", "cancelled")),
            )
        )
    ).scalars().all()

    for listing in listings:
        listing.status = "cancelled"
        listing.is_public = False

    channels = (
        await db.execute(
            select(Channel).where(Channel.owner_id == user.id)
        )
    ).scalars().all()

    for channel in channels:
        channel.is_active = False
        channel.is_listed = False

    user.is_active = False

    await db.commit()

    return {
        "status": "success",
        "user_id": user.id,
        "listings_cancelled": len(listings),
        "channels_removed": len(channels),
    }


# ============================================================
# ANNONCE À TOUS LES UTILISATEURS (via le bot)
# ============================================================

async def _broadcast(admin_chat_id: int, chat_ids: list[int], text: str) -> None:
    bot = get_telegram_service().bot
    sent = failed = 0

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception:
            # utilisateur qui a bloqué le bot / jamais démarré le bot
            failed += 1

        await asyncio.sleep(0.06)  # ~16 messages/s : sous la limite Telegram

    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=f"📢 Annonce terminée : {sent} envoyé(s), {failed} non distribué(s).",
        )
    except Exception:
        pass


_broadcast_tasks: set = set()


@router.post("/announcements")
async def send_announcement(
    payload: AnnouncementRequest,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    if payload.audience == "me":
        chat_ids = [current_admin.telegram_id]
    else:
        chat_ids = [
            int(value)
            for (value,) in (
                await db.execute(
                    select(User.telegram_id).where(User.is_active.is_(True))
                )
            ).all()
        ]

    task = asyncio.get_running_loop().create_task(
        _broadcast(
            current_admin.telegram_id,
            chat_ids,
            "📢 NexMarket\n\n" + payload.text.strip(),
        )
    )
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)

    return {"status": "queued", "recipients": len(chat_ids)}


# ============================================================
# ADMINISTRATEURS
# ============================================================

@router.get("/admins")
async def list_admins(
    current_admin: CurrentAdmin,
    db: DBSession,
):
    rows = (
        await db.execute(
            select(User)
            .where(
                or_(
                    User.is_admin.is_(True),
                    User.telegram_id == int(settings.ADMIN_TELEGRAM_ID or 0),
                )
            )
            .order_by(User.created_at)
        )
    ).scalars().all()

    return {
        "admins": [
            {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "nexa_id": user.nexa_id,
                "name": " ".join(
                    part for part in (user.first_name, user.last_name) if part
                ) or user.username,
                "username": user.username,
                "is_primary": bool(
                    settings.ADMIN_TELEGRAM_ID
                    and user.telegram_id == int(settings.ADMIN_TELEGRAM_ID)
                ),
            }
            for user in rows
        ]
    }
