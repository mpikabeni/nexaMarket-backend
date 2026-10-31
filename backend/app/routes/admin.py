from datetime import datetime, timezone
import hmac

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    status,
)
from pydantic import BaseModel
from sqlalchemy import func, select

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
from app.models.schemas import RejectRequest
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


@router.post("/login")
async def admin_login(
    payload: AdminLoginRequest,
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

    if not settings.ADMIN_TELEGRAM_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "L'identifiant Telegram administrateur "
                "n'est pas configuré."
            ),
        )

    if not settings.ADMIN_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Le code administrateur "
                "n'est pas configuré."
            ),
        )

    # --------------------------------------------------------
    # Vérification du code administrateur
    # --------------------------------------------------------

    if not payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le code administrateur est obligatoire.",
        )

    if not hmac.compare_digest(
        str(payload.code),
        str(settings.ADMIN_CODE),
    ):
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
    # Vérification que c'est bien l'administrateur
    # --------------------------------------------------------

    if telegram_id != int(
        settings.ADMIN_TELEGRAM_ID
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Vous n'êtes pas autorisé "
                "à accéder à l'administration."
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
    Liste les annonces en attente de modération.
    """

    result = await db.execute(
        select(Listing)
        .where(
            Listing.status == "pending_review"
        )
        .order_by(
            Listing.created_at.asc()
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
                "platform_fee_rate": (
                    listing.platform_fee_rate
                ),
                "created_at": listing.created_at,
            }
            for listing in listings
        ],
        "count": len(listings),
    }


# ============================================================
# APPROVE LISTING
# ============================================================

@router.post("/listings/{listing_id}/approve")
async def approve_listing(
    listing_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
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
