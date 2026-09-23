# ============================================================
# NEXMARKET
# backend/app/routes/admin.py
# ============================================================

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
import jwt
from jwt import InvalidTokenError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.models.channel import Channel
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.report import Report
from app.models.wallet import Wallet
from app.models.platform import PlatformWallet, PlatformLedger
from app.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminListingDecision,
    AdminTransactionAction,
)


router = APIRouter(
    prefix="/admin",
    tags=["Administration"],
)


# ============================================================
# ADMIN TOKEN
# ============================================================

def create_admin_token() -> str:

    expires = datetime.utcnow() + timedelta(
        minutes=settings.ADMIN_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "type": "admin",
        "exp": expires,
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def get_admin_token(
    authorization: str | None = Header(
        default=None,
    ),
) -> str:

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token administrateur requis.",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Format du token invalide.",
        )

    return authorization.replace(
        "Bearer ",
        "",
        1,
    ).strip()


def require_admin_token(
    authorization: str | None = Header(
        default=None,
    ),
):
    token = get_admin_token(authorization)

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token administrateur invalide ou expiré.",
        ) from exc

    if payload.get("type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token non administrateur.",
        )

    return payload


# ============================================================
# LOGIN ADMIN
# ============================================================

@router.post(
    "/login",
    response_model=AdminLoginResponse,
)
def admin_login(
    payload: AdminLoginRequest,
):

    if payload.code != settings.ADMIN_CODE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Code administrateur incorrect.",
        )

    token = create_admin_token()

    return {
        "token": token,
        "expires_in": (
            settings.ADMIN_TOKEN_EXPIRE_MINUTES * 60
        ),
    }


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/dashboard")
def admin_dashboard(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    users = db.query(User).count()

    channels = db.query(Channel).count()

    listings = db.query(Listing).count()

    pending_listings = (
        db.query(Listing)
        .filter(Listing.status == "pending")
        .count()
    )

    transactions = db.query(Transaction).count()

    pending_transactions = (
        db.query(Transaction)
        .filter(
            Transaction.status.in_(
                [
                    "pending_payment",
                    "payment_confirmed",
                    "waiting_admin",
                    "assigned",
                    "transfer_pending",
                    "disputed",
                ]
            )
        )
        .count()
    )

    reports = db.query(Report).count()

    pending_reports = (
        db.query(Report)
        .filter(
            Report.status.in_(
                [
                    "pending",
                    "reviewing",
                ]
            )
        )
        .count()
    )

    platform_wallet = (
        db.query(PlatformWallet)
        .first()
    )

    platform_balance = (
        platform_wallet.balance
        if platform_wallet
        else 0
    )

    return {
        "success": True,
        "stats": {
            "users": users,
            "channels": channels,
            "listings": listings,
            "pending_listings": pending_listings,
            "transactions": transactions,
            "pending_transactions": pending_transactions,
            "reports": reports,
            "pending_reports": pending_reports,
            "platform_balance": platform_balance,
        },
    }


# ============================================================
# ANNONCES EN ATTENTE
# ============================================================

@router.get("/listings/pending")
def pending_listings(
    _: dict = Depends(require_admin_token),
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

    return {
        "success": True,
        "count": len(listings),
        "listings": [
            {
                "id": listing.id,
                "channel_id": listing.channel_id,
                "seller_id": listing.seller_id,
                "price": listing.price,
                "currency": listing.currency,
                "description": listing.description,
                "status": listing.status,
                "publish_fee": listing.publish_fee,
                "publish_fee_paid": listing.publish_fee_paid,
                "created_at": listing.created_at,
            }
            for listing in listings
        ],
    }


# ============================================================
# VALIDER / REFUSER UNE ANNONCE
# ============================================================

@router.post("/listings/{listing_id}/decision")
def listing_decision(
    listing_id: int,
    payload: AdminListingDecision,
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    action = payload.action.strip().lower()

    if action not in {
        "approve",
        "approve",
        "reject",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Action invalide. "
                "Utilisez approve ou reject."
            ),
        )

    if action in {
        "approve",
        "approved",
    }:

        listing.status = "available"
        listing.admin_note = payload.note
        listing.validated_at = datetime.utcnow()

        listing.validated_by_id = None

    else:

        listing.status = "rejected"
        listing.admin_note = payload.note
        listing.validated_at = datetime.utcnow()

    db.commit()
    db.refresh(listing)

    return {
        "success": True,
        "message": (
            "Annonce approuvée."
            if action in {"approve", "approved"}
            else "Annonce refusée."
        ),
        "listing_id": listing.id,
        "status": listing.status,
    }


# ============================================================
# LISTE DES TRANSACTIONS
# ============================================================

@router.get("/transactions")
def admin_transactions(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    transactions = (
        db.query(Transaction)
        .order_by(
            Transaction.created_at.desc()
        )
        .all()
    )

    return {
        "success": True,
        "count": len(transactions),
        "transactions": [
            {
                "id": transaction.id,
                "reference": transaction.reference,
                "listing_id": transaction.listing_id,
                "buyer_id": transaction.buyer_id,
                "seller_id": transaction.seller_id,
                "assigned_admin_id": transaction.assigned_admin_id,
                "channel_price": transaction.channel_price,
                "platform_fee": transaction.platform_fee,
                "provider_fee": transaction.provider_fee,
                "total_buyer_amount": transaction.total_buyer_amount,
                "seller_amount": transaction.seller_amount,
                "currency": transaction.currency,
                "status": transaction.status,
                "payment_provider": transaction.payment_provider,
                "payment_reference": transaction.payment_reference,
                "payment_status": transaction.payment_status,
                "created_at": transaction.created_at,
                "updated_at": transaction.updated_at,
            }
            for transaction in transactions
        ],
    }


# ============================================================
# PRENDRE EN CHARGE UNE TRANSACTION
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    # Le token admin ne contient pas d'ID utilisateur.
    # L'assignation définitive à un compte admin Telegram
    # sera faite dans le workflow admin authentifié.
    #
    # Pour l'instant on passe la transaction en "assigned".
    transaction.status = "assigned"
    transaction.assigned_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "Transaction prise en charge.",
        "transaction_id": transaction.id,
        "status": transaction.status,
    }


# ============================================================
# COMMENCER LE TRANSFERT
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    if transaction.status not in {
        "assigned",
        "waiting_admin",
        "payment_confirmed",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cette transaction ne peut pas "
                "encore commencer le transfert."
            ),
        )

    transaction.status = "transfer_pending"
    transaction.transfer_started_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "Transfert Telegram démarré.",
        "transaction_id": transaction.id,
        "status": transaction.status,
    }


# ============================================================
# ANNULER UNE TRANSACTION
# ============================================================

@router.post("/transactions/{transaction_id}/cancel")
def cancel_transaction(
    transaction_id: int,
    payload: AdminTransactionAction,
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    if transaction.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Une transaction terminée ne peut pas être annulée.",
        )

    transaction.status = "cancelled"
    transaction.cancellation_reason = (
        payload.note or "Annulée par l'administration."
    )
    transaction.cancelled_at = datetime.utcnow()

    listing = (
        db.query(Listing)
        .filter(
            Listing.id == transaction.listing_id
        )
        .first()
    )

    if listing and listing.status == "reserved":
        listing.status = "available"
        listing.locked_price = None
        listing.locked_at = None

    db.commit()

    return {
        "success": True,
        "message": "Transaction annulée.",
        "transaction_id": transaction.id,
        "status": transaction.status,
    }


# ============================================================
# LITIGES
# ============================================================

@router.get("/reports")
def admin_reports(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    reports = (
        db.query(Report)
        .order_by(
            Report.created_at.desc()
        )
        .all()
    )

    return {
        "success": True,
        "count": len(reports),
        "reports": [
            {
                "id": report.id,
                "reporter_id": report.reporter_id,
                "listing_id": report.listing_id,
                "transaction_id": report.transaction_id,
                "reason": report.reason,
                "description": report.description,
                "status": report.status,
                "admin_note": report.admin_note,
                "resolved_by_id": report.resolved_by_id,
                "created_at": report.created_at,
                "resolved_at": report.resolved_at,
            }
            for report in reports
        ],
    }


@router.post("/reports/{report_id}/resolve")
def resolve_report(
    report_id: int,
    payload: AdminTransactionAction,
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    report = (
        db.query(Report)
        .filter(Report.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signalement introuvable.",
        )

    action = payload.action.strip().lower()

    if action not in {
        "resolve",
        "reject",
        "review",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Action invalide. "
                "Utilisez resolve, reject ou review."
            ),
        )

    if action == "resolve":
        report.status = "resolved"
        report.resolved_at = datetime.utcnow()

    elif action == "reject":
        report.status = "rejected"
        report.resolved_at = datetime.utcnow()

    else:
        report.status = "reviewing"

    report.admin_note = payload.note

    db.commit()

    return {
        "success": True,
        "report_id": report.id,
        "status": report.status,
    }


# ============================================================
# UTILISATEURS
# ============================================================

@router.get("/users")
def admin_users(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    users = (
        db.query(User)
        .order_by(
            User.created_at.desc()
        )
        .all()
    )

    return {
        "success": True,
        "count": len(users),
        "users": [
            {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "nexa_id": user.nexa_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "photo_url": user.photo_url,
                "is_active": user.is_active,
                "is_admin": user.is_admin,
                "language": user.language,
                "currency": user.currency,
                "created_at": user.created_at,
            }
            for user in users
        ],
    }


# ============================================================
# ACTIVER / DÉSACTIVER UN UTILISATEUR
# ============================================================

@router.patch("/users/{user_id}/status")
def change_user_status(
    user_id: int,
    active: bool,
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )

    user.is_active = active

    db.commit()

    return {
        "success": True,
        "user_id": user.id,
        "is_active": user.is_active,
    }


# ============================================================
# CANAUX
# ============================================================

@router.get("/channels")
def admin_channels(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    channels = (
        db.query(Channel)
        .order_by(
            Channel.created_at.desc()
        )
        .all()
    )

    return {
        "success": True,
        "count": len(channels),
        "channels": [
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
                "owner_id": channel.owner_id,
                "is_active": channel.is_active,
                "created_at": channel.created_at,
            }
            for channel in channels
        ],
    }


# ============================================================
# PORTEFEUILLE PLATEFORME
# ============================================================

@router.get("/wallet")
def admin_wallet(
    _: dict = Depends(require_admin_token),
    db: Session = Depends(get_db),
):

    wallet = (
        db.query(PlatformWallet)
        .first()
    )

    if not wallet:
        wallet = PlatformWallet(
            balance=0,
            currency=settings.DEFAULT_CURRENCY,
        )

        db.add(wallet)
        db.commit()
        db.refresh(wallet)

    ledger = (
        db.query(PlatformLedger)
        .order_by(
            PlatformLedger.created_at.desc()
        )
        .limit(100)
        .all()
    )

    return {
        "success": True,
        "balance": wallet.balance,
        "currency": wallet.currency,
        "ledger": [
            {
                "id": item.id,
                "reference": item.reference,
                "operation_type": item.operation_type,
                "amount": item.amount,
                "currency": item.currency,
                "direction": item.direction,
                "description": item.description,
                "transaction_id": item.transaction_id,
                "created_at": item.created_at,
            }
            for item in ledger
        ],
    }


# ============================================================
# TEST ADMIN
# ============================================================

@router.get("/me")
def admin_me(
    _: dict = Depends(require_admin_token),
):

    return {
        "success": True,
        "role": "admin",
        "name": "NEXA",
    }
