from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, status
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
# OUTILS ADMIN
# ============================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_admin_token() -> str:
    """
    Crée un JWT pour l'espace administrateur.
    """

    now = utcnow()

    payload = {
        "sub": "nexmarket_admin",
        "type": "admin",
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(hours=12)).timestamp()
        ),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_admin_token(token: str) -> dict:
    """
    Vérifie le JWT administrateur.
    """

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session administrateur expirée",
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token administrateur invalide",
        )

    if payload.get("type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès administrateur requis",
        )

    return payload


def require_admin(
    authorization: Optional[str] = Header(
        default=None,
        alias="Authorization",
    ),
):
    """
    Vérifie l'en-tête :
    Authorization: Bearer TOKEN
    """

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization manquante",
        )

    parts = authorization.split(" ", 1)

    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Format Authorization invalide",
        )

    scheme, token = parts

    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token requis",
        )

    if not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token manquant",
        )

    return decode_admin_token(token.strip())


# ============================================================
# LOGIN
# ============================================================

@router.post(
    "/login",
    response_model=AdminLoginResponse,
)
def admin_login(
    data: AdminLoginRequest,
):
    """
    Connexion administrateur avec ADMIN_CODE.
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

    return AdminLoginResponse(
        token=token,
        expires_in=12 * 60 * 60,
    )


# ============================================================
# ADMIN / ME
# ============================================================

@router.get("/me")
def admin_me(
    _: dict = Depends(require_admin),
):
    return {
        "authenticated": True,
        "role": "admin",
        "name": "NEXA",
    }


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/dashboard")
def dashboard(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users_count = (
        db.query(func.count(User.id)).scalar()
        or 0
    )

    channels_count = (
        db.query(func.count(Channel.id)).scalar()
        or 0
    )

    listings_count = (
        db.query(func.count(Listing.id)).scalar()
        or 0
    )

    pending_listings = (
        db.query(func.count(Listing.id))
        .filter(
            Listing.status == "pending"
        )
        .scalar()
        or 0
    )

    available_listings = (
        db.query(func.count(Listing.id))
        .filter(
            Listing.status == "available"
        )
        .scalar()
        or 0
    )

    transactions_count = (
        db.query(
            func.count(Transaction.id)
        ).scalar()
        or 0
    )

    pending_transactions = (
        db.query(
            func.count(Transaction.id)
        )
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

    open_reports = (
        db.query(
            func.count(Report.id)
        )
        .filter(
            Report.status.in_(
                [
                    "pending",
                    "reviewing",
                ]
            )
        )
        .scalar()
        or 0
    )

    platform_wallet = (
        db.query(PlatformWallet).first()
    )

    platform_balance = 0.0
    platform_currency = (
        settings.DEFAULT_CURRENCY
    )

    if platform_wallet:
        platform_balance = float(
            platform_wallet.balance or 0
        )
        platform_currency = (
            platform_wallet.currency
        )

    return {
        "users": users_count,
        "channels": channels_count,
        "listings": listings_count,
        "pending_listings": pending_listings,
        "available_listings": available_listings,
        "transactions": transactions_count,
        "pending_transactions": pending_transactions,
        "open_reports": open_reports,
        "platform_balance": platform_balance,
        "platform_currency": platform_currency,
    }


# ============================================================
# LISTINGS EN ATTENTE
# ============================================================

@router.get("/listings/pending")
def get_pending_listings(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    listings = (
        db.query(Listing)
        .filter(
            Listing.status == "pending"
        )
        .order_by(
            Listing.created_at.asc()
        )
        .all()
    )

    result = []

    for listing in listings:

        channel = (
            db.query(Channel)
            .filter(
                Channel.id
                == listing.channel_id
            )
            .first()
        )

        seller = (
            db.query(User)
            .filter(
                User.id
                == listing.seller_id
            )
            .first()
        )

        result.append(
            {
                "id": listing.id,
                "channel_id": listing.channel_id,
                "seller_id": listing.seller_id,
                "price": float(
                    listing.price
                ),
                "currency": listing.currency,
                "description": listing.description,
                "status": listing.status,
                "publish_fee": float(
                    listing.publish_fee or 0
                ),
                "publish_fee_paid": (
                    listing.publish_fee_paid
                ),
                "admin_note": listing.admin_note,
                "created_at": listing.created_at,
                "channel": (
                    {
                        "id": channel.id,
                        "title": channel.title,
                        "username": channel.username,
                        "description": channel.description,
                        "photo_url": channel.photo_url,
                        "category": channel.category,
                        "country": channel.country,
                        "language": channel.language,
                        "subscribers_count": (
                            channel.subscribers_count
                        ),
                        "telegram_verified": (
                            channel.telegram_verified
                        ),
                        "bot_is_admin": (
                            channel.bot_is_admin
                        ),
                        "seller_is_admin": (
                            channel.seller_is_admin
                        ),
                        "is_active": (
                            channel.is_active
                        ),
                    }
                    if channel
                    else None
                ),
                "seller": (
                    {
                        "id": seller.id,
                        "nexa_id": seller.nexa_id,
                        "username": seller.username,
                        "first_name": seller.first_name,
                        "last_name": seller.last_name,
                    }
                    if seller
                    else None
                ),
            }
        )

    return result


# ============================================================
# DÉCISION SUR UNE ANNONCE
# ============================================================

@router.post(
    "/listings/{listing_id}/decision"
)
def listing_decision(
    listing_id: int,
    data: AdminListingDecision,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable",
        )

    action = (
        data.action
        .strip()
        .lower()
    )

    if action not in {
        "approve",
        "reject",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Action invalide. "
                "Utilisez approve ou reject."
            ),
        )

    now = utcnow()

    if action == "approve":

        listing.status = "available"
        listing.admin_note = data.note
        listing.validated_at = now

        channel = (
            db.query(Channel)
            .filter(
                Channel.id
                == listing.channel_id
            )
            .first()
        )

        if channel:
            channel.is_active = True

        message = "Annonce approuvée"

    else:

        listing.status = "rejected"
        listing.admin_note = data.note

        message = "Annonce rejetée"

    db.commit()
    db.refresh(listing)

    return {
        "success": True,
        "listing_id": listing.id,
        "status": listing.status,
        "message": message,
    }


# ============================================================
# TRANSACTIONS
# ============================================================

@router.get("/transactions")
def get_transactions(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    transactions = (
        db.query(Transaction)
        .order_by(
            Transaction.created_at.desc()
        )
        .all()
    )

    result = []

    for transaction in transactions:

        buyer = (
            db.query(User)
            .filter(
                User.id
                == transaction.buyer_id
            )
            .first()
        )

        seller = (
            db.query(User)
            .filter(
                User.id
                == transaction.seller_id
            )
            .first()
        )

        listing = (
            db.query(Listing)
            .filter(
                Listing.id
                == transaction.listing_id
            )
            .first()
        )

        channel = None

        if listing:
            channel = (
                db.query(Channel)
                .filter(
                    Channel.id
                    == listing.channel_id
                )
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
                "created_at": transaction.created_at,
                "updated_at": transaction.updated_at,
                "buyer": (
                    {
                        "id": buyer.id,
                        "nexa_id": buyer.nexa_id,
                        "username": buyer.username,
                        "first_name": buyer.first_name,
                        "last_name": buyer.last_name,
                    }
                    if buyer
                    else None
                ),
                "seller": (
                    {
                        "id": seller.id,
                        "nexa_id": seller.nexa_id,
                        "username": seller.username,
                        "first_name": seller.first_name,
                        "last_name": seller.last_name,
                    }
                    if seller
                    else None
                ),
                "channel": (
                    {
                        "id": channel.id,
                        "title": channel.title,
                        "username": channel.username,
                    }
                    if channel
                    else None
                ),
                "assigned_admin": (
                    {
                        "id": assigned_admin.id,
                        "nexa_id": (
                            assigned_admin.nexa_id
                        ),
                        "username": (
                            assigned_admin.username
                        ),
                    }
                    if assigned_admin
                    else None
                ),
            }
        )

    return result


# ============================================================
# ASSIGNER UNE TRANSACTION
# ============================================================

@router.post(
    "/transactions/{transaction_id}/assign"
)
def assign_transaction(
    transaction_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    transaction = (
        db.query(Transaction)
        .filter(
            Transaction.id
            == transaction_id
        )
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
            detail=(
                "Cette transaction est déjà terminée."
            ),
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

@router.post(
    "/transactions/{transaction_id}/start-transfer"
)
def start_transfer(
    transaction_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    transaction = (
        db.query(Transaction)
        .filter(
            Transaction.id
            == transaction_id
        )
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable",
        )

    allowed_statuses = {
        "assigned",
        "waiting_admin",
        "payment_confirmed",
    }

    if transaction.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                "La transaction ne peut pas "
                "encore commencer le transfert."
            ),
        )

    transaction.status = "transfer_pending"

    transaction.transfer_started_at = utcnow()

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

@router.post(
    "/transactions/{transaction_id}/complete"
)
def complete_transaction(
    transaction_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    transaction = (
        db.query(Transaction)
        .filter(
            Transaction.id
            == transaction_id
        )
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
            "message": (
                "Transaction déjà terminée."
            ),
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
