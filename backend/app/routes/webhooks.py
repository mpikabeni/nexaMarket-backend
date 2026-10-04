from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request

from app.db import AsyncSessionLocal
from app.models import User
from app.services.jessikapay import (
    JessiKaPayError,
    jessikapay_service,
)
from app.services.wallet_service import (
    WalletService,
    WalletServiceError,
)
from sqlalchemy import select


router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


@router.post("/jessikapay")
async def jessikapay_webhook(request: Request):
    """
    Reçoit les événements JessiKaPay.

    Événements pris en charge :
    - deposit.completed
    - payment.completed
    - credit.completed

    Aucun mécanisme de signature webhook n'est inventé ici,
    car la documentation fournie ne définit pas de signature
    entrante.

    Le traitement doit rester idempotent grâce aux références
    JessiKaPay enregistrées dans les opérations du wallet.
    """

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Payload JSON invalide.",
        ) from exc

    event = payload.get("event")

    if not event:
        raise HTTPException(
            status_code=400,
            detail="Événement JessiKaPay manquant.",
        )

    # ========================================================
    # DEPOSIT COMPLETED
    # ========================================================

    if event == "deposit.completed":
        request_id = payload.get("request_id")
        telegram_id = payload.get("telegram_id")
        amount = payload.get("amount")
        reference = payload.get("reference")

        if not request_id:
            raise HTTPException(
                status_code=400,
                detail="request_id manquant.",
            )

        if not telegram_id:
            raise HTTPException(
                status_code=400,
                detail="telegram_id manquant.",
            )

        if amount is None:
            raise HTTPException(
                status_code=400,
                detail="amount manquant.",
            )

        if not reference:
            raise HTTPException(
                status_code=400,
                detail="reference manquante.",
            )

        try:
            amount_decimal = Decimal(str(amount))
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Montant invalide.",
            ) from exc

        if amount_decimal <= 0:
            raise HTTPException(
                status_code=400,
                detail="Le montant doit être supérieur à zéro.",
            )

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(
                    User.telegram_id == int(telegram_id)
                )
            )

            user = result.scalar_one_or_none()

            if user is None:
                raise HTTPException(
                    status_code=404,
                    detail="Utilisateur NexMarket introuvable.",
                )

            wallet_service = WalletService(db)

            try:
                wallet = await wallet_service.credit(
                    user_id=user.id,
                    amount=amount_decimal,
                    reference=str(reference),
                    operation_type="deposit",
                    provider_reference=str(request_id),
                    description=(
                        "Dépôt confirmé par JessiKaPay"
                    ),
                )

            except WalletServiceError as exc:
                # Si l'opération existe déjà, le webhook a
                # probablement été reçu une seconde fois.
                if "déjà été enregistrée" in str(exc):
                    return {
                        "received": True,
                        "event": event,
                        "status": "already_processed",
                        "reference": reference,
                    }

                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

        return {
            "received": True,
            "event": event,
            "status": "processed",
            "request_id": request_id,
            "reference": reference,
            "amount": amount,
            "wallet_balance": wallet.available_balance,
        }

    # ========================================================
    # PAYMENT COMPLETED
    # ========================================================

    if event == "payment.completed":
        return {
            "received": True,
            "event": event,
            "status": "received",
        }

    # ========================================================
    # CREDIT COMPLETED
    # ========================================================

    if event == "credit.completed":
        return {
            "received": True,
            "event": event,
            "status": "received",
        }

    # ========================================================
    # EVENT INCONNU
    # ========================================================

    return {
        "received": True,
        "event": event,
        "status": "ignored",
    }
