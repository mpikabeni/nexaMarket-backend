from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.channel import Channel
from app.models.listing import Listing
from app.models.message import Message
from app.models.platform import PlatformLedger, PlatformWallet
from app.models.report import Report
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet, WalletOperation
from app.schemas import AdminListingDecision, AdminLoginRequest, AdminLoginResponse, AdminTransactionAction

router = APIRouter(prefix="/admin", tags=["admin"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def val(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def admin_required(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Accès administrateur requis.")
    return user


def wallet(db: Session, user_id: int) -> Wallet:
    w = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not w:
        w = Wallet(user_id=user_id, available_balance=0, blocked_balance=0, total_revenue=0, currency=settings.DEFAULT_CURRENCY)
        db.add(w)
        db.flush()
    return w


def platform_wallet(db: Session) -> PlatformWallet:
    w = db.query(PlatformWallet).first()
    if not w:
        w = PlatformWallet(balance=0, currency=settings.DEFAULT_CURRENCY)
        db.add(w)
        db.flush()
    return w


def listing_out(x: Listing) -> dict:
    c = x.channel
    s = x.seller
    return {
        "id": x.id, "channel_id": x.channel_id, "seller_id": x.seller_id,
        "price": val(x.price), "currency": x.currency, "description": x.description,
        "status": x.status, "locked_price": val(x.locked_price),
        "publish_fee": val(x.publish_fee), "publish_fee_paid": x.publish_fee_paid,
        "admin_note": x.admin_note, "validated_by_id": x.validated_by_id,
        "validated_at": val(x.validated_at), "created_at": val(x.created_at), "updated_at": val(x.updated_at),
        "channel": ({"id": c.id, "title": c.title, "username": c.username, "photo_url": c.photo_url,
                     "category": c.category, "country": c.country, "language": c.language,
                     "subscribers_count": c.subscribers_count, "telegram_verified": c.telegram_verified,
                     "bot_is_admin": c.bot_is_admin, "seller_is_admin": c.seller_is_admin} if c else None),
        "seller": ({"id": s.id, "nexa_id": s.nexa_id, "telegram_id": s.telegram_id,
                    "username": s.username, "first_name": s.first_name, "last_name": s.last_name} if s else None),
    }


def tx_out(x: Transaction) -> dict:
    return {
        "id": x.id, "reference": x.reference, "listing_id": x.listing_id,
        "buyer_id": x.buyer_id, "seller_id": x.seller_id, "assigned_admin_id": x.assigned_admin_id,
        "channel_price": val(x.channel_price), "platform_fee": val(x.platform_fee),
        "provider_fee": val(x.provider_fee), "total_buyer_amount": val(x.total_buyer_amount),
        "seller_amount": val(x.seller_amount), "currency": x.currency, "status": x.status,
        "payment_provider": x.payment_provider, "payment_reference": x.payment_reference,
        "payment_status": x.payment_status, "telegram_chat_id": x.telegram_chat_id,
        "transfer_started_at": val(x.transfer_started_at), "completed_at": val(x.completed_at),
        "cancelled_at": val(x.cancelled_at), "admin_note": x.admin_note,
        "cancellation_reason": x.cancellation_reason, "dispute_reason": x.dispute_reason,
        "created_at": val(x.created_at), "updated_at": val(x.updated_at),
    }


@router.post("/login", response_model=AdminLoginResponse)
def login(data: AdminLoginRequest, db: Session = Depends(get_db)):
    if data.code != settings.ADMIN_CODE:
        raise HTTPException(401, "Code administrateur incorrect.")
    user = db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True)).order_by(User.id).first()
    if not user:
        raise HTTPException(503, "Aucun compte administrateur Telegram actif.")
    t = now()
    token = jwt.encode({"sub": str(user.id), "telegram_id": str(user.telegram_id), "is_admin": True,
                        "iat": int(t.timestamp()), "exp": int((t + timedelta(hours=8)).timestamp())},
                       settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return AdminLoginResponse(token=token, expires_in=28800)


@router.get("/me")
def me(user: User = Depends(admin_required)):
    return {"id": user.id, "nexa_id": user.nexa_id, "telegram_id": user.telegram_id,
            "username": user.username, "first_name": user.first_name, "last_name": user.last_name,
            "is_admin": user.is_admin}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(admin_required)):
    active = ["pending_payment", "payment_confirmed", "waiting_admin", "assigned", "transfer_pending", "disputed"]
    p = platform_wallet(db)
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "channels": db.query(func.count(Channel.id)).scalar() or 0,
        "listings": db.query(func.count(Listing.id)).scalar() or 0,
        "pending_listings": db.query(func.count(Listing.id)).filter(Listing.status == "pending").scalar() or 0,
        "transactions": db.query(func.count(Transaction.id)).scalar() or 0,
        "active_transactions": db.query(func.count(Transaction.id)).filter(Transaction.status.in_(active)).scalar() or 0,
        "pending_reports": db.query(func.count(Report.id)).filter(Report.status.in_(["pending", "reviewing"])).scalar() or 0,
        "platform_wallet": {"balance": val(p.balance), "currency": p.currency},
    }


@router.get("/listings")
def listings(status: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
             db: Session = Depends(get_db), _: User = Depends(admin_required)):
    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == status)
    if q:
        p = f"%{q.strip().lower()}%"
        query = query.join(Channel).filter(or_(func.lower(Channel.title).like(p), func.lower(Channel.username).like(p), func.lower(Listing.description).like(p)))
    total = query.count()
    rows = query.order_by(Listing.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [listing_out(x) for x in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/verifications")
def verifications(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(admin_required)):
    q = db.query(Listing).filter(Listing.status == "pending")
    total = q.count()
    rows = q.order_by(Listing.created_at.asc()).offset(offset).limit(limit).all()
    return {"items": [listing_out(x) for x in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/listings/{listing_id}")
def listing(listing_id: int, db: Session = Depends(get_db), _: User = Depends(admin_required)):
    x = db.query(Listing).filter(Listing.id == listing_id).first()
    if not x:
        raise HTTPException(404, "Annonce introuvable.")
    return listing_out(x)


@router.post("/listings/{listing_id}/decision")
def listing_decision(listing_id: int, data: AdminListingDecision, db: Session = Depends(get_db), user: User = Depends(admin_required)):
    x = db.query(Listing).filter(Listing.id == listing_id).first()
    if not x:
        raise HTTPException(404, "Annonce introuvable.")
    action = data.action.strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(400, "Action invalide: approve ou reject.")
    x.status = "available" if action == "approve" else "rejected"
    x.validated_by_id = user.id
    x.validated_at = now()
    x.admin_note = data.note
    db.commit()
    db.refresh(x)
    return {"status": "ok", "action": action, "listing": listing_out(x)}


@router.get("/transactions")
def transactions(status: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), _: User = Depends(admin_required)):
    query = db.query(Transaction)
    if status:
        query = query.filter(Transaction.status == status)
    if q:
        p = f"%{q.strip().lower()}%"
        query = query.filter(func.lower(Transaction.reference).like(p))
    total = query.count()
    rows = query.order_by(Transaction.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [tx_out(x) for x in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/transactions/{transaction_id}")
def transaction(transaction_id: int, db: Session = Depends(get_db), _: User = Depends(admin_required)):
    x = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not x:
        raise HTTPException(404, "Transaction introuvable.")
    return tx_out(x)


@router.post("/transactions/{transaction_id}/action")
def transaction_action(transaction_id: int, data: AdminTransactionAction, db: Session = Depends(get_db), user: User = Depends(admin_required)):
    x = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not x:
        raise HTTPException(404, "Transaction introuvable.")
    action = data.action.strip().lower()
    note = data.note

    if action in {"assign", "take_charge", "prendre_en_charge"}:
        if x.status in {"completed", "cancelled", "refunded"}:
            raise HTTPException(400, "Transaction déjà terminée.")
        x.assigned_admin_id = user.id
        if x.status in {"waiting_admin", "payment_confirmed"}:
            x.status = "assigned"
        x.admin_note = note
        db.commit(); db.refresh(x)
        return {"status": "ok", "transaction": tx_out(x)}

    if action in {"start_transfer", "transfer"}:
        if x.status not in {"assigned", "waiting_admin", "payment_confirmed"}:
            raise HTTPException(400, "Transaction non prête pour le transfert.")
        x.assigned_admin_id = user.id
        x.status = "transfer_pending"
        x.transfer_started_at = now()
        x.admin_note = note
        db.commit(); db.refresh(x)
        return {"status": "ok", "transaction": tx_out(x)}

    if action in {"complete", "completed"}:
        if x.status == "completed":
            return {"status": "ok", "transaction": tx_out(x)}
        if x.status in {"cancelled", "refunded"}:
            raise HTTPException(400, "Transaction annulée.")
        bw = wallet(db, x.buyer_id); sw = wallet(db, x.seller_id); pw = platform_wallet(db)
        total = Decimal(str(x.total_buyer_amount or 0)); fee = Decimal(str(x.platform_fee or 0)); seller_amount = Decimal(str(x.seller_amount or 0))
        if Decimal(str(bw.blocked_balance or 0)) < total:
            raise HTTPException(409, "Solde bloqué insuffisant.")
        bw.blocked_balance -= total
        sw.available_balance += seller_amount
        sw.total_revenue += seller_amount
        if fee > 0:
            pw.balance += fee
            db.add(PlatformLedger(reference=f"TX-{x.reference}", operation_type="platform_fee", amount=fee,
                                  currency=x.currency, direction="credit", description=f"Commission NexMarket - {x.reference}", transaction_id=x.id))
        db.add(WalletOperation(user_id=x.seller_id, operation_type="sale_revenue", amount=seller_amount,
                               currency=x.currency, status="completed", reference=x.reference,
                               description=f"Revenu de vente - {x.reference}", completed_at=now()))
        l = db.query(Listing).filter(Listing.id == x.listing_id).first()
        if l: l.status = "sold"
        x.assigned_admin_id = user.id; x.status = "completed"; x.completed_at = now(); x.admin_note = note
        db.commit(); db.refresh(x)
        return {"status": "ok", "transaction": tx_out(x)}

    if action in {"cancel", "cancelled", "refund"}:
        if x.status == "completed":
            raise HTTPException(400, "Transaction déjà terminée.")
        bw = wallet(db, x.buyer_id); total = Decimal(str(x.total_buyer_amount or 0))
        blocked = Decimal(str(bw.blocked_balance or 0)); release = min(blocked, total)
        bw.blocked_balance -= release; bw.available_balance += release
        if release > 0:
            db.add(WalletOperation(user_id=x.buyer_id, operation_type="refund", amount=release, currency=x.currency,
                                   status="completed", reference=x.reference, description=f"Remboursement - {x.reference}", completed_at=now()))
        l = db.query(Listing).filter(Listing.id == x.listing_id).first()
        if l and l.status == "reserved": l.status = "available"
        x.assigned_admin_id = user.id; x.status = "cancelled"; x.cancelled_at = now()
        x.cancellation_reason = note or "Annulation par l'administrateur."; x.admin_note = note
        db.commit(); db.refresh(x)
        return {"status": "ok", "transaction": tx_out(x)}

    if action in {"dispute", "open_dispute"}:
        x.assigned_admin_id = user.id; x.status = "disputed"; x.dispute_reason = note or "Litige ouvert par l'administrateur."; x.admin_note = note
        db.commit(); db.refresh(x)
        return {"status": "ok", "transaction": tx_out(x)}

    raise HTTPException(400, "Action administrateur inconnue.")


@router.get("/users")
def users(q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(admin_required)):
    query = db.query(User)
    if q:
        p = f"%{q.strip().lower()}%"
        query = query.filter(or_(func.lower(User.username).like(p), func.lower(User.first_name).like(p), func.lower(User.last_name).like(p), func.lower(User.nexa_id).like(p)))
    total = query.count(); rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    out = []
    for u in rows:
        w = db.query(Wallet).filter(Wallet.user_id == u.id).first()
        out.append({"id": u.id, "telegram_id": u.telegram_id, "nexa_id": u.nexa_id, "username": u.username,
                    "first_name": u.first_name, "last_name": u.last_name, "photo_url": u.photo_url,
                    "language": u.language, "currency": u.currency, "is_active": u.is_active, "is_admin": u.is_admin,
                    "created_at": val(u.created_at), "wallet": ({"available_balance": val(w.available_balance), "blocked_balance": val(w.blocked_balance), "total_revenue": val(w.total_revenue), "currency": w.currency} if w else None)})
    return {"items": out, "total": total, "limit": limit, "offset": offset}


@router.patch("/users/{user_id}/admin")
def set_admin(user_id: int, is_admin: bool = Query(...), db: Session = Depends(get_db), user: User = Depends(admin_required)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target: raise HTTPException(404, "Utilisateur introuvable.")
    if target.id == user.id and not is_admin: raise HTTPException(400, "Vous ne pouvez pas retirer vos propres droits.")
    target.is_admin = is_admin; db.commit()
    return {"status": "ok", "user_id": target.id, "is_admin": target.is_admin}


@router.get("/channels")
def channels(q: str | None = None, active: bool | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(admin_required)):
    query = db.query(Channel)
    if active is not None: query = query.filter(Channel.is_active == active)
    if q:
        p = f"%{q.strip().lower()}%"; query = query.filter(or_(func.lower(Channel.title).like(p), func.lower(Channel.username).like(p)))
    total = query.count(); rows = query.order_by(Channel.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [{"id": c.id, "telegram_chat_id": c.telegram_chat_id, "title": c.title, "username": c.username,
                        "description": c.description, "photo_url": c.photo_url, "category": c.category, "country": c.country,
                        "language": c.language, "subscribers_count": c.subscribers_count, "telegram_verified": c.telegram_verified,
                        "bot_is_admin": c.bot_is_admin, "seller_is_admin": c.seller_is_admin, "verification_note": c.verification_note,
                        "verified_at": val(c.verified_at), "owner_id": c.owner_id, "is_active": c.is_active,
                        "created_at": val(c.created_at), "updated_at": val(c.updated_at)} for c in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/reports")
def reports(status: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(admin_required)):
    query = db.query(Report)
    if status: query = query.filter(Report.status == status)
    total = query.count(); rows = query.order_by(Report.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [{"id": r.id, "reporter_id": r.reporter_id, "listing_id": r.listing_id, "transaction_id": r.transaction_id,
                        "reason": r.reason, "description": r.description, "status": r.status, "admin_note": r.admin_note,
                        "resolved_by_id": r.resolved_by_id, "created_at": val(r.created_at), "resolved_at": val(r.resolved_at)} for r in rows],
            "total": total, "limit": limit, "offset": offset}


@router.post("/reports/{report_id}/resolve")
def resolve_report(report_id: int, status: str = Query(..., pattern="^(resolved|rejected|reviewing)$"), note: str | None = None,
                   db: Session = Depends(get_db), user: User = Depends(admin_required)):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r: raise HTTPException(404, "Signalement introuvable.")
    r.status = status; r.admin_note = note; r.resolved_by_id = user.id; r.resolved_at = now(); db.commit()
    return {"status": "ok", "report_id": r.id, "report_status": r.status}


@router.get("/wallet")
def admin_wallet(db: Session = Depends(get_db), _: User = Depends(admin_required)):
    w = platform_wallet(db)
    return {"balance": val(w.balance), "currency": w.currency}


@router.get("/wallet/operations")
def wallet_operations(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(admin_required)):
    rows = db.query(PlatformLedger).order_by(PlatformLedger.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [{"id": x.id, "reference": x.reference, "operation_type": x.operation_type, "amount": val(x.amount),
                        "currency": x.currency, "direction": x.direction, "description": x.description,
                        "transaction_id": x.transaction_id, "created_at": val(x.created_at)} for x in rows], "limit": limit, "offset": offset}


@router.get("/messages")
def messages(transaction_id: int | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(admin_required)):
    query = db.query(Message)
    if transaction_id is not None: query = query.filter(Message.transaction_id == transaction_id)
    rows = query.order_by(Message.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [{"id": m.id, "transaction_id": m.transaction_id, "sender_id": m.sender_id, "content": m.content,
                        "message_type": m.message_type, "media_url": m.media_url, "media_type": m.media_type,
                        "is_system_message": m.is_system_message, "is_read": m.is_read, "created_at": val(m.created_at)} for m in rows],
            "limit": limit, "offset": offset}
