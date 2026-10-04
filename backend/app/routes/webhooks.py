from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import User
from app.models.withdrawal import Withdrawal

from app.services.wallet_service import (
    WalletService,
    WalletServiceError,
)


router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


@router.post("/jessikapay")
async def jessikapay_webhook(request: Request):
    """
    Réception des événements JessiKaPay.

    Événements :
    - deposit.completed
    - payment.completed
    - credit.completed

    La documentation JessiKaPay fournie ne définit pas
    de signature entrante pour les webhooks. Nous n'en
    inventons donc pas.

    Les opérations financières sont rendues idempotentes
    grâce aux références enregistrées dans NexMarket.
    """

    # ========================================================
    # READ PAYLOAD
    # ========================================================

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

        try:
            telegram_id_int = int(telegram_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="telegram_id invalide.",
            ) from exc

        async with AsyncSessionLocal() as db:

            # ------------------------------------------------
            # FIND USER
            # ------------------------------------------------

            result = await db.execute(
                select(User).where(
                    User.telegram_id == telegram_id_int
                )
            )

            user = result.scalar_one_or_none()

            if user is None:
                raise HTTPException(
                    status_code=404,
                    detail="Utilisateur NexMarket introuvable.",
                )

            wallet_service = WalletService(db)

            # ------------------------------------------------
            # CREDIT WALLET
            # ------------------------------------------------

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

                # Webhook reçu une deuxième fois.
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
            "amount": float(amount_decimal),
            "wallet_balance": float(
                wallet.available_balance
            ),
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

        transaction_id = payload.get(
            "transaction_id"
        )

        jp_number = payload.get(
            "jp_number"
        )

        telegram_id = payload.get(
            "telegram_id"
        )

        amount = payload.get(
            "amount"
        )

        reference = payload.get(
            "reference"
        )

        if not transaction_id:
            raise HTTPException(
                status_code=400,
                detail="transaction_id manquant.",
            )

        if not jp_number:
            raise HTTPException(
                status_code=400,
                detail="jp_number manquant.",
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
            amount_decimal = Decimal(
                str(amount)
            )
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

            # ------------------------------------------------
            # FIND WITHDRAWAL
            # ------------------------------------------------

            result = await db.execute(
                select(Withdrawal).where(
                    Withdrawal.reference
                    == str(reference)
                )
            )

            withdrawal = (
                result.scalar_one_or_none()
            )

            if withdrawal is None:
                # On ne consomme aucun fonds si la référence
                # ne correspond pas à un retrait NexMarket.
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Retrait NexMarket introuvable "
                        "pour cette référence."
                    ),
                )

            # ------------------------------------------------
            # IDEMPOTENCE
            # ------------------------------------------------

            if withdrawal.status == "completed":
                return {
                    "received": True,
                    "event": event,
                    "status": "already_processed",
                    "reference": reference,
                    "transaction_id": transaction_id,
                }

            # ------------------------------------------------
            # VERIFY BASIC DATA
            # ------------------------------------------------

            if (
                withdrawal.jessikapay_jp_number
                and str(
                    withdrawal.jessikapay_jp_number
                ) != str(jp_number)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Le numéro JessiKaPay du webhook "
                        "ne correspond pas au retrait."
                    ),
                )

            withdrawal_amount = Decimal(
                str(withdrawal.amount)
            )

            if withdrawal_amount != amount_decimal:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Le montant du webhook "
                        "ne correspond pas au retrait."
                    ),
                )

            # ------------------------------------------------
            # PROVIDER REFERENCE
            # ------------------------------------------------

            if (
                withdrawal.provider_reference
                and str(
                    withdrawal.provider_reference
                ) != str(transaction_id)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Le transaction_id JessiKaPay "
                        "ne correspond pas au retrait."
                    ),
                )

            # ------------------------------------------------
            # CONSUME BLOCKED FUNDS
            # ------------------------------------------------

            wallet_service = WalletService(db)

            consume_reference = (
                f"{reference}-CONSUME"
            )

            try:
                wallet = (
                    await wallet_service.consume_blocked(
                        user_id=withdrawal.user_id,
                        amount=amount_decimal,
                        reference=consume_reference,
                        description=(
                            "Retrait confirmé par JessiKaPay"
                        ),
                    )
                )

            except WalletServiceError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

            # ------------------------------------------------
            # UPDATE WITHDRAWAL
            # ------------------------------------------------

            withdrawal.provider_reference = str(
                transaction_id
            )

            withdrawal.status = "completed"

            await db.commit()

        return {
            "received": True,
            "event": event,
            "status": "processed",
            "reference": reference,
            "transaction_id": transaction_id,
            "jp_number": jp_number,
            "amount": float(amount_decimal),
            "withdrawal_status": "completed",
            "wallet_balance": float(
                wallet.available_balance
            ),
        }

    # ========================================================
    # UNKNOWN EVENT
    # ========================================================

    return {
        "received": True,
        "event": event,
        "status": "ignored",
    }
