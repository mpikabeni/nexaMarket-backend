from __future__ import annotations

from datetime import datetime
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
    Webhook JessiKaPay.

    Événements gérés :
        - deposit.completed
        - payment.completed
        - credit.completed

    La documentation JessiKaPay fournie ne définit pas
    de signature entrante pour les webhooks.
    Aucune signature n'est donc inventée ici.
    """

    # ========================================================
    # LECTURE DU PAYLOAD
    # ========================================================

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Payload JSON invalide.",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Payload webhook invalide.",
        )

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

        if telegram_id is None:
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
            telegram_id = int(telegram_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="telegram_id invalide.",
            ) from exc

        try:
            amount_decimal = Decimal(
                str(amount)
            ).quantize(
                Decimal("0.01")
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
            # UTILISATEUR
            # ------------------------------------------------

            result = await db.execute(
                select(User).where(
                    User.telegram_id == telegram_id
                )
            )

            user = result.scalar_one_or_none()

            if user is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Utilisateur NexMarket "
                        "introuvable."
                    ),
                )

            wallet_service = WalletService(db)

            # ------------------------------------------------
            # CRÉDIT DU WALLET
            # ------------------------------------------------

            try:
                wallet = await wallet_service.credit(
                    user_id=user.id,
                    amount=amount_decimal,
                    reference=str(reference),
                    operation_type="deposit",
                    provider_reference=str(
                        request_id
                    ),
                    description=(
                        "Dépôt confirmé par JessiKaPay"
                    ),
                )

            except WalletServiceError as exc:

                # Webhook reçu plusieurs fois.
                if (
                    "déjà été enregistrée"
                    in str(exc)
                ):
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
            "request_id": str(request_id),
            "reference": str(reference),
            "amount": float(
                amount_decimal
            ),
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
            ).quantize(
                Decimal("0.01")
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
            # RETRAIT NEXMARKET
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
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Retrait NexMarket "
                        "introuvable."
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
                    "transaction_id": (
                        transaction_id
                    ),
                }

            # ------------------------------------------------
            # VÉRIFICATION DU JP
            # ------------------------------------------------

            if (
                str(
                    withdrawal.jessikapay_jp_number
                )
                != str(jp_number)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Le numéro JessiKaPay "
                        "ne correspond pas au retrait."
                    ),
                )

            # ------------------------------------------------
            # VÉRIFICATION DU MONTANT
            # ------------------------------------------------

            withdrawal_amount = Decimal(
                str(withdrawal.amount)
            ).quantize(
                Decimal("0.01")
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
            # VÉRIFICATION TRANSACTION ID
            # ------------------------------------------------

            if (
                withdrawal.jessikapay_transaction_id
                and str(
                    withdrawal.jessikapay_transaction_id
                )
                != str(transaction_id)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Le transaction_id JessiKaPay "
                        "ne correspond pas au retrait."
                    ),
                )

            # ------------------------------------------------
            # CONSOMMATION DES FONDS BLOQUÉS
            # ------------------------------------------------

            wallet_service = WalletService(db)

            try:
                wallet = (
                    await wallet_service.consume_blocked(
                        user_id=withdrawal.user_id,
                        amount=amount_decimal,
                        reference=(
                            f"{reference}-CONSUME"
                        ),
                        description=(
                            "Retrait confirmé "
                            "par JessiKaPay"
                        ),
                    )
                )

            except WalletServiceError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

            # ------------------------------------------------
            # FINALISATION DU RETRAIT
            # ------------------------------------------------

            withdrawal.jessikapay_transaction_id = (
                str(transaction_id)
            )

            withdrawal.status = "completed"

            withdrawal.completed_at = (
                datetime.utcnow()
            )

            await db.commit()

        return {
            "received": True,
            "event": event,
            "status": "processed",
            "reference": str(reference),
            "transaction_id": str(
                transaction_id
            ),
            "jp_number": str(jp_number),
            "amount": float(
                amount_decimal
            ),
            "withdrawal_status": "completed",
            "wallet_balance": float(
                wallet.available_balance
            ),
        }

    # ========================================================
    # ÉVÉNEMENT INCONNU
    # ========================================================

    return {
        "received": True,
        "event": event,
        "status": "ignored",
    }
