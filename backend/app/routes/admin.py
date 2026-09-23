from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas import (
    AdminListingDecision,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminTransactionAction,
)
from app.models.user import User
from app.models.listings import Listing
from app.models.channel import Channel
from app.models.transaction import Transaction
from app.models.report import Report
from app.models.wallet import Wallet
from app.models.platform import PlatformWallet, PlatformLedger


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


# ============================================================
# UTILITAIRES JWT ADMIN
# ============================================================

def create_admin_token() -> str:
    """
    Crée un token JWT destiné uniquement à l'espace administrateur.
    """

    now = datetime.now(timezone.utc)

    payload = {
        "sub": "nexmarket_admin",
        "type": "admin",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=12)).timestamp()),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_admin_token(token: str) -> dict:
    """
    Vérifie et décode le token administrateur.
    """

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token administrateur invalide ou expiré",
        )

    if payload.get("type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès administrateur requis",
        )

    return payload


def get_admin_token(
    authorization: str | None = None,
) -> str:
    """
    Extrait le Bearer token de l'en-tête Authorization.
    """

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization manquante",
        )

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Format Authorization invalide",
        )

    return authorization.split(" ", 1)[1].strip()


def require_admin_token(
    authorization: str | None = None,
):
    """
    Dépendance utilisée pour protéger les routes admin.
    """

    token = get_admin_token(authorization)

    return decode_admin_token(token)


# ============================================================
# LOGIN ADMIN
# ============================================================

@router.post(
    "/login",
    response_model=AdminLoginResponse,
)
def admin_login(
    data: AdminLoginRequest,
):
    """
    Connexion à l'espace administrateur avec ADMIN_CODE.
    """

    if not settings.ADMIN_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_CODE non configuré",
        )

    if data.code != settings.ADMIN_CODE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Code administrateur incorrect",
        )

    token = create_admin_token()

    return {
        "token": token,
        "expires_in": 12 * 60 * 60,
    }


# ============================================================
# INFORMATIONS ADMIN
# ============================================================

@router.get("/me")
def admin_me(
    _: dict = Depends(require_admin_token),
):
    return {
        "authenticated": True,
        "role": "admin",
    }


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/dashboard")
def dashboard(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    users_count = db.query(func.count(User.id)).scalar() or 0

    channels_count = db.query(func.count(Channel.id)).scalar() or 0

    listings_count = db.query(func.count(Listing.id)).scalar() or 0

    pending_listings = (
        db.query(func.count(Listing.id))
        .filter(Listing.status == "pending")
        .scalar()
        or 0
    )

    available_listings = (
        db.query(func.count(Listing.id))
        .filter(Listing.status == "available")
        .scalar()
        or 0
    )

    transactions_count = (
        db.query(func.count(Transaction.id)).scalar() or 0
    )

    pending_transactions = (
        db.query(func.count(Transaction.id))
        .filter(
            Transaction.status.in_(
                [
                    "pending_payment",
                    "payment_confirmed",
                    "waiting_admin",
                    "assigned",
                    "transfer_pending",
                ]
            )
        )
        .scalar()
        or 0
    )

    reports_count = (
        db.query(func.count(Report.id))
        .filter(
            Report.status.in_(
                ["pending", "reviewing"]
            )
        )
        .scalar()
        or 0
    )

    platform_wallet = (
        db.query(PlatformWallet).first()
    )

    platform_balance = (
        float(platform_wallet.balance)
        if platform_wallet
        else 0.0
    )

    return {
        "users": users_count,
        "channels": channels_count,
        "listings": listings_count,
        "pending_listings": pending_listings,
        "available_listings": available_listings,
        "transactions": transactions_count,
        "pending_transactions": pending_transactions,
        "open_reports": reports_count,
        "platform_balance": platform_balance,
    }


# ============================================================
# LISTINGS À VALIDER
# ============================================================

@router.get("/listings/pending")
def pending_listings(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    listings = (
        db.query(Listing)
        .filter(Listing.status == "pending")
        .order_by(Listing.created_at.asc())
        .all()
    )

    result = []

    for listing in listings:
        channel = (
            db.query(Channel)
            .filter(Channel.id == listing.channel_id)
            .first()
        )

        seller = (
            db.query(User)
            .filter(User.id == listing.seller_id)
            .first()
        )

        result.append(
            {
                "id": listing.id,
                "channel_id": listing.channel_id,
                "channel": {
                    "title": channel.title if channel else None,
                    "username": channel.username if channel else None,
                    "subscribers_count": (
                        channel.subscribers_count
                        if channel
                        else 0
                    ),
                    "category": (
                        channel.category
                        if channel
                        else None
                    ),
                    "country": (
                        channel.country
                        if channel
                        else None
                    ),
                    "language": (
                        channel.language
                        if channel
                        else None
                    ),
                    "telegram_verified": (
                        channel.telegram_verified
                        if channel
                        else False
                    ),
                    "bot_is_admin": (
                        channel.bot_is_admin
                        if channel
                        else False
                    ),
                    "seller_is_admin": (
                        channel.seller_is_admin
                        if channel
                        else False
                    ),
                },
                "seller": {
                    "id": seller.id if seller else None,
                    "nexa_id": seller.nexa_id if seller else None,
                    "username": seller.username if seller else None,
                    "first_name": seller.first_name if seller else None,
                },
                "price": float(listing.price),
                "currency": listing.currency,
                "description": listing.description,
                "status": listing.status,
                "publish_fee": float(listing.publish_fee or 0),
                "publish_fee_paid": listing.publish_fee_paid,
                "created_at": listing.created_at,
            }
        )

    return result


# ============================================================
# VALIDATION D'UNE ANNONCE
# ============================================================

@router.post("/listings/{listing_id}/decision")
def listing_decision(
    listing_id: int,
    data: AdminListingDecision,
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    listing = (
        db.query(Listing)
        .filter(Listing.id == listing_id)
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable",
        )

    action = data.action.lower().strip()

    if action not in {"approve", "reject"}:
        raise HTTPException(
            status_code=400,
            detail="Action invalide. Utilisez approve ou reject.",
        )

    if action == "approve":
        listing.status = "available"
        listing.admin_note = data.note
        listing.validated_at = datetime.now(timezone.utc)

        channel = (
            db.query(Channel)
            .filter(Channel.id == listing.channel_id)
            .first()
        )

        if channel:
            channel.is_active = True

    else:
        listing.status = "rejected"
        listing.admin_note = data.note

    db.commit()
    db.refresh(listing)

    return {
        "success": True,
        "listing_id": listing.id,
        "status": listing.status,
        "message": (
            "Annonce approuvée"
            if action == "approve"
            else "Annonce rejetée"
        ),
    }


# ============================================================
# TRANSACTIONS
# ============================================================

@router.get("/transactions")
def admin_transactions(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    transactions = (
        db.query(Transaction)
        .order_by(Transaction.created_at.desc())
        .all()
    )

    result = []

    for transaction in transactions:

        buyer = (
            db.query(User)
            .filter(User.id == transaction.buyer_id)
            .first()
        )

        seller = (
            db.query(User)
            .filter(User.id == transaction.seller_id)
            .first()
        )

        listing = (
            db.query(Listing)
            .filter(Listing.id == transaction.listing_id)
            .first()
        )

        channel = None

        if listing:
            channel = (
                db.query(Channel)
                .filter(Channel.id == listing.channel_id)
                .first()
            )

        assigned_admin = None

        if transaction.assigned_admin_id:
            assigned_admin = (
                db.query(User)
                .filter(
                    User.id
                    == transaction.assigned_admin_id
                )
                .first()
            )

        result.append(
            {
                "id": transaction.id,
                "reference": transaction.reference,
                "status": transaction.status,
                "channel_price": float(
                    transaction.channel_price
                ),
                "platform_fee": float(
                    transaction.platform_fee
                ),
                "provider_fee": float(
                    transaction.provider_fee
                ),
                "total_buyer_amount": float(
                    transaction.total_buyer_amount
                ),
                "seller_amount": float(
                    transaction.seller_amount
                ),
                "currency": transaction.currency,
                "payment_provider": (
                    transaction.payment_provider
                ),
                "payment_reference": (
                    transaction.payment_reference
                ),
                "payment_status": (
                    transaction.payment_status
                ),
                "telegram_chat_id": (
                    transaction.telegram_chat_id
                ),
                "buyer": {
                    "id": buyer.id if buyer else None,
                    "nexa_id": (
                        buyer.nexa_id
                        if buyer
                        else None
                    ),
                    "username": (
                        buyer.username
                        if buyer
                        else None
                    ),
                    "first_name": (
                        buyer.first_name
                        if buyer
                        else None
                    ),
                },
                "seller": {
                    "id": seller.id if seller else None,
                    "nexa_id": (
                        seller.nexa_id
                        if seller
                        else None
                    ),
                    "username": (
                        seller.username
                        if seller
                        else None
                    ),
                    "first_name": (
                        seller.first_name
                        if seller
                        else None
                    ),
                },
                "channel": {
                    "title": (
                        channel.title
                        if channel
                        else None
                    ),
                    "username": (
                        channel.username
                        if channel
                        else None
                    ),
                },
                "assigned_admin": {
                    "id": (
                        assigned_admin.id
                        if assigned_admin
                        else None
                    ),
                    "username": (
                        assigned_admin.username
                        if assigned_admin
                        else None
                    ),
                }
                if assigned_admin
                else None,
                "created_at": transaction.created_at,
                "updated_at": transaction.updated_at,
            }
        )

    return result


# ============================================================
# ASSIGNER UNE TRANSACTION
# ============================================================

@router.post("/transactions/{transaction_id}/assign")
def assign_transaction(
    transaction_id: int,
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable",
        )

    if transaction.status in {
        "completed",
        "cancelled",
        "refunded",
    }:
        raise HTTPException(
            status_code=400,
            detail="Cette transaction est déjà terminée.",
        )

    transaction.status = "assigned"

    db.commit()
    db.refresh(transaction)

    return {
        "success": True,
        "transaction_id": transaction.id,
        "status": transaction.status,
    }


# ============================================================
# DÉMARRER LE TRANSFERT
# ============================================================

@router.post("/transactions/{transaction_id}/start-transfer")
def start_transfer(
    transaction_id: int,
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable",
        )

    if transaction.status not in {
        "assigned",
        "waiting_admin",
        "payment_confirmed",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "La transaction ne peut pas "
                "encore commencer le transfert."
            ),
        )

    transaction.status = "transfer_pending"

    transaction.transfer_started_at = (
        datetime.now(timezone.utc)
    )

    db.commit()
    db.refresh(transaction)

    return {
        "success": True,
        "transaction_id": transaction.id,
        "status": transaction.status,
    }


# ============================================================
# TERMINER UNE TRANSACTION
# ============================================================

@router.post("/transactions/{transaction_id}/complete")
def complete_transaction(
    transaction_id: int,
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable",
        )

    if transaction.status == "completed":
        return {
            "success": True,
            "transaction_id": transaction.id,
            "status": "completed",
            "message": "Transaction déjà terminée.",
        }

    if transaction.status not in {
        "transfer_pending",
        "assigned",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "La transaction doit être "
                "en cours de transfert."
            ),
        )

    buyer_wallet = (
        db.query(Wallet)
        .filter(
            Wallet.user_id
            == transaction.buyer_id
        )
        .first()
    )

    seller_wallet = (
        db.query(Wallet)
        .filter(
            Wallet.user_id
            == transaction.seller_id
        )
        .first()
    )

    if not buyer_wallet:
        raise HTTPException(
            status_code=400,
            detail="Portefeuille acheteur introuvable.",
        )

    if not seller_wallet:
        raise HTTPException(
            status_code=400,
            detail="Portefeuille vendeur introuvable.",
        )

    total = float(transaction.total_buyer_amount)
    seller_amount = float(transaction.seller_amount)
    platform_fee = float(transaction.platform_fee)

    blocked = float(
        buyer_wallet.blocked_balance or 0
    )

    if blocked < total:
        raise HTTPException(
            status_code=400,
            detail=(
                "Les fonds bloqués de l'acheteur "
                "sont insuffisants."
            ),
        )

    # Retrait des fonds bloqués
    buyer_wallet.blocked_balance = (
        blocked - total
    )

    # Crédit vendeur
    seller_wallet.available_balance = (
        float(seller_wallet.available_balance or 0)
        + seller_amount
    )

    seller_wallet.total_revenue = (
        float(seller_wallet.total_reve
