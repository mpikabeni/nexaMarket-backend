from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.services.jessikapay import (
    JessiKaPayError,
    jessikapay_service,
)
from app.services.wallet_service import (
    WalletService,
    WalletServiceError,
)


router = APIRouter(
    prefix="/withdrawals",
    tags=["Withdrawals"],
)


# ============================================================
# CREATE WITHDRAWAL
# ============================================================

@router.post("")
async def request_withdrawal(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Crée un retrait vers un numéro JessiKaPay.

    Le montant est d'abord bloqué dans le wallet NexMarket,
    puis envoyé à JessiKaPay.

    Le retrait passe en processing jusqu'à la réception
    de l'événement credit.completed.
    """

    raw_amount = payload.get("amount", 0)

    jp_number = str(
        payload.get("jp_number", "")
    ).strip()

    if not jp_number:
        raise HTTPException(
            status_code=400,
            detail="Numéro JessiKaPay requis.",
        )

    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Montant invalide.",
        )

    amount = amount.quantize(
        Decimal("0.01")
    )

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Le montant doit être supérieur à zéro.",
        )

    # ========================================================
    # WALLET
    # ========================================================

    wallet_service = WalletService(db)

    try:
        wallet = await wallet_service.get_wallet(
            user.id
        )
    except WalletServiceError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    available_balance = Decimal(
        str(wallet.available_balance or 0)
    )

    if available_balance < amount:
        raise HTTPException(
            status_code=400,
            detail="Solde insuffisant.",
        )

    # ========================================================
    # UNIQUE REFERENCE
    # ========================================================

    reference = (
        f"WD-{user.id}-"
        f"{uuid4().hex[:16].upper()}"
    )

    # ========================================================
    # BLOCK FUNDS
    # ========================================================

    try:
        await wallet_service.block(
            user_id=user.id,
            amount=amount,
            reference=reference,
            description=(
                "Fonds bloqués pour retrait JessiKaPay"
            ),
        )

    except WalletServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # ========================================================
    # CREATE WITHDRAWAL
    # ========================================================

    withdrawal = Withdrawal(
        user_id=user.id,
        reference=reference,
        amount=amount,
        currency="XAF",
        jessikapay_jp_number=jp_number,
        status="pending",
    )

    db.add(withdrawal)

    await db.commit()
    await db.refresh(withdrawal)

    # ========================================================
    # JESSIKAPAY PAYOUT
    # ========================================================

    payout_payload = {
        "jp_number": jp_number,
        "amount": float(amount),
        "reference": reference,
        "description": (
            f"NexMarket withdrawal {reference}"
        ),
    }

    try:
        payout_response = (
            await jessikapay_service.payout(
                payout_payload
            )
        )

    except JessiKaPayError as exc:

        # Libérer les fonds si JessiKaPay
        # refuse ou échoue immédiatement.

        try:
            await wallet_service.release_blocked(
                user_id=user.id,
                amount=amount,
                reference=f"{reference}-RELEASE",
                description=(
                    "Libération des fonds après "
                    "échec du payout JessiKaPay"
                ),
            )

        except WalletServiceError as release_exc:
            withdrawal.failure_reason = (
                f"JessiKaPay: {exc}; "
                f"Release: {release_exc}"
            )

        else:
            withdrawal.failure_reason = str(exc)

        withdrawal.status = "failed"

        await db.commit()

        raise HTTPException(
            status_code=502,
            detail=f"Erreur JessiKaPay : {exc}",
        ) from exc

    # ========================================================
    # SAVE JESSIKAPAY TRANSACTION
    # ========================================================

    transaction_id = payout_response.get(
        "transaction_id"
    )

    if transaction_id:
        withdrawal.jessikapay_transaction_id = str(
            transaction_id
        )

    withdrawal.status = "processing"
    withdrawal.processed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(withdrawal)

    return {
        "success": True,
        "id": withdrawal.id,
        "reference": withdrawal.reference,
        "provider": "jessikapay",
        "jessikapay_transaction_id": (
            withdrawal.jessikapay_transaction_id
        ),
        "jp_number": withdrawal.jessikapay_jp_number,
        "amount": float(withdrawal.amount),
        "currency": withdrawal.currency,
        "status": withdrawal.status,
        "message": (
            "Votre retrait est en cours de traitement."
        ),
    }

    # À ajouter dans app/routes/withdrawals.py

@router.get("/lookup/{jp_number}")
async def lookup_jp(
    jp_number: str,
    user: User = Depends(get_current_user),
):
    """Vérifie directement un compte JessiKaPay sans choisir de pays."""
    jp_number = jp_number.strip().upper()

    import re
    if not re.fullmatch(r"JP-\d{6}", jp_number):
        raise HTTPException(
            status_code=400,
            detail="Le numéro JessiKaPay doit être au format JP-222222.",
        )

    try:
        result = await jessikapay_service.lookup_jp(jp_number)
    except JessiKaPayError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur JessiKaPay : {exc}",
        ) from exc

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=502,
            detail="Réponse JessiKaPay invalide.",
        )

    if not result.get("found"):
        return {"found": False}

    return {
        "found": True,
        "jp_number": result.get("jp_number") or jp_number,
        "name": result.get("name") or "",
        "first_name": result.get("first_name") or "",
        "last_name": result.get("last_name") or "",
        "photo_url": result.get("photo_url") or "",
    }
    
# ============================================================
# MY WITHDRAWALS
# ============================================================

@router.get("/mine")
async def mine(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Retourne les retraits de l'utilisateur connecté.
    """

    result = await db.execute(
        select(Withdrawal)
        .where(
            Withdrawal.user_id == user.id
        )
        .order_by(
            Withdrawal.created_at.desc()
        )
    )

    withdrawals = result.scalars().all()

    return [
        {
            "id": withdrawal.id,
            "reference": withdrawal.reference,
            "amount": float(
                withdrawal.amount
            ),
            "currency": withdrawal.currency,
            "status": withdrawal.status,
            "jp_number": (
                withdrawal.jessikapay_jp_number
            ),
            "jessikapay_transaction_id": (
                withdrawal.jessikapay_transaction_id
            ),
            "failure_reason": (
                withdrawal.failure_reason
            ),
            "created_at": (
                withdrawal.created_at.isoformat()
                if withdrawal.created_at
                else None
            ),
            "processed_at": (
                withdrawal.processed_at.isoformat()
                if withdrawal.processed_at
                else None
            ),
            "completed_at": (
                withdrawal.completed_at.isoformat()
                if withdrawal.completed_at
                else None
            ),
        }
        for withdrawal in withdrawals
    ]
