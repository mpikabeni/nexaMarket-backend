from __future__ import annotations

import hmac
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.deposit import Deposit
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.services.wallet_service import (
    DuplicateOperationError,
    WalletService,
    WalletServiceError,
)


router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


# ============================================================
# AUTHENTIFICATION DU WEBHOOK
# ============================================================
#
# SÉCURITÉ : avant, n'importe qui pouvant deviner l'URL pouvait envoyer
# un faux "deposit.completed" et se créditer de l'argent gratuitement.
#
# Le webhook exige maintenant un secret partagé (JESSIKAPAY_WEBHOOK_SECRET),
# envoyé dans l'en-tête X-Webhook-Secret ou dans l'URL (?token=...).
# Si le secret n'est pas configuré, le webhook REFUSE tout (fail closed).
#
# De plus, chaque événement est recoupé avec nos propres enregistrements
# (dépôt, retrait, transaction) : montant, utilisateur et statut.
# ============================================================

def _require_secret(request: Request) -> None:
    secret = settings.JESSIKAPAY_WEBHOOK_SECRET

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Webhook non configuré.",
        )

    provided = (
        request.headers.get("X-Webhook-Secret")
        or request.query_params.get("token")
        or ""
    )

    if not hmac.compare_digest(
        provided.encode("utf-8"),
        secret.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=401,
            detail="Webhook non autorisé.",
        )


def _parse_amount(raw) -> Decimal:
    try:
        amount = Decimal(str(raw)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Montant invalide.",
        ) from exc

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Le montant doit être supérieur à zéro.",
        )

    return amount


def _require(payload: dict, *keys: str) -> None:
    for key in keys:
        if payload.get(key) in (None, ""):
            raise HTTPException(
                status_code=400,
                detail=f"{key} manquant.",
            )


# ============================================================
# ENDPOINT
# ============================================================

@router.post("/jessikapay")
async def jessikapay_webhook(request: Request):
    """
    Événements gérés (JessiKaPay ne sert qu'aux dépôts et retraits) :
        - deposit.completed  : dépôt dans le wallet
        - credit.completed   : retrait utilisateur terminé
    """

    _require_secret(request)

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

    if event == "deposit.completed":
        return await _handle_deposit_completed(payload)

    if event == "credit.completed":
        return await _handle_credit_completed(payload)

    return {
        "received": True,
        "event": event,
        "status": "ignored",
    }


# ============================================================
# DEPOSIT COMPLETED
# ============================================================

async def _handle_deposit_completed(payload: dict) -> dict:
    _require(payload, "request_id", "telegram_id", "amount", "reference")

    reference = str(payload["reference"])
    request_id = str(payload["request_id"])
    amount = _parse_amount(payload["amount"])

    try:
        telegram_id = int(payload["telegram_id"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="telegram_id invalide.",
        ) from exc

    async with AsyncSessionLocal() as db:

        # Le dépôt DOIT exister chez nous : on ne crédite jamais
        # sur la seule foi du contenu du webhook.
        result = await db.execute(
            select(Deposit)
            .where(Deposit.reference == reference)
            .with_for_update()
        )

        deposit = result.scalar_one_or_none()

        if deposit is None:
            raise HTTPException(
                status_code=404,
                detail="Dépôt introuvable.",
            )

        if deposit.jessikapay_request_id != request_id:
            raise HTTPException(
                status_code=409,
                detail="request_id ne correspond pas au dépôt.",
            )

        user_result = await db.execute(
            select(User).where(User.id == deposit.user_id)
        )

        user = user_result.scalar_one_or_none()

        if user is None or user.telegram_id != telegram_id:
            raise HTTPException(
                status_code=409,
                detail="Utilisateur ne correspondant pas au dépôt.",
            )

        deposit_amount = Decimal(str(deposit.amount)).quantize(
            Decimal("0.01")
        )

        if deposit_amount != amount:
            raise HTTPException(
                status_code=409,
                detail="Montant ne correspondant pas au dépôt.",
            )

        wallet_service = WalletService(db)

        already = False

        try:
            wallet = await wallet_service.credit(
                user_id=deposit.user_id,
                amount=amount,
                reference=reference,
                operation_type="deposit",
                provider_reference=request_id,
                description="Dépôt confirmé par JessiKaPay",
            )
        except DuplicateOperationError:
            already = True
            wallet = await wallet_service.get_wallet(deposit.user_id)
        except WalletServiceError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc

        # Met à jour le dépôt (avant : il restait "pending" à vie).
        if deposit.status != "paid":
            deposit.status = "paid"
            deposit.webhook_received = True
            deposit.paid_at = datetime.utcnow()
            await db.commit()

        return {
            "received": True,
            "event": "deposit.completed",
            "status": "already_processed" if already else "processed",
            "reference": reference,
            "wallet_balance": float(wallet.available_balance),
        }


# ============================================================
# CREDIT COMPLETED (retrait utilisateur)
# ============================================================

async def _handle_credit_completed(payload: dict) -> dict:
    _require(payload, "transaction_id", "jp_number", "amount", "reference")

    transaction_id = str(payload["transaction_id"])
    jp_number = str(payload["jp_number"])
    reference = str(payload["reference"])
    amount = _parse_amount(payload["amount"])

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(Withdrawal)
            .where(Withdrawal.reference == reference)
            .with_for_update()
        )

        withdrawal = result.scalar_one_or_none()

        if withdrawal is None:
            raise HTTPException(
                status_code=404,
                detail="Retrait NexMarket introuvable.",
            )

        # ----------------------------------------------------
        # Retrait utilisateur
        # ----------------------------------------------------

        if withdrawal.status == "completed":
            return {
                "received": True,
                "event": "credit.completed",
                "status": "already_processed",
                "reference": reference,
                "transaction_id": transaction_id,
            }

        if withdrawal.status not in ("pending", "processing"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Le retrait est dans un état "
                    f"« {withdrawal.status} » : confirmation refusée."
                ),
            )

        if str(withdrawal.jessikapay_jp_number) != jp_number:
            raise HTTPException(
                status_code=409,
                detail="Le numéro JessiKaPay ne correspond pas au retrait.",
            )

        withdrawal_amount = Decimal(str(withdrawal.amount)).quantize(
            Decimal("0.01")
        )

        if withdrawal_amount != amount:
            raise HTTPException(
                status_code=409,
                detail="Le montant du webhook ne correspond pas au retrait.",
            )

        if (
            withdrawal.jessikapay_transaction_id
            and str(withdrawal.jessikapay_transaction_id) != transaction_id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Le transaction_id JessiKaPay ne correspond "
                    "pas au retrait."
                ),
            )

        wallet_service = WalletService(db)

        try:
            wallet = await wallet_service.consume_blocked(
                user_id=withdrawal.user_id,
                amount=amount,
                reference=f"{reference}-CONSUME",
                description="Retrait confirmé par JessiKaPay",
            )
        except DuplicateOperationError:
            # Fonds déjà consommés lors d'un essai précédent
            # interrompu avant la mise à jour du retrait.
            wallet = await wallet_service.get_wallet(withdrawal.user_id)
        except WalletServiceError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc

        withdrawal.jessikapay_transaction_id = transaction_id
        withdrawal.status = "completed"
        withdrawal.completed_at = datetime.utcnow()

        await db.commit()

        return {
            "received": True,
            "event": "credit.completed",
            "status": "processed",
            "reference": reference,
            "transaction_id": transaction_id,
            "jp_number": jp_number,
            "amount": float(amount),
            "withdrawal_status": "completed",
            "wallet_balance": float(wallet.available_balance),
        }
