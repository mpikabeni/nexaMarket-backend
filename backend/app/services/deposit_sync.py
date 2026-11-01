"""
Vérification des dépôts SANS webhook.

JessiKaPay n'appelle plus NexMarket : c'est NexMarket qui interroge le
point d'état du prestataire (GET /external/v1/deposit-request/{id}/status)
- à la demande de l'utilisateur (POST /deposits/{id}/check) ;
- en tâche de fond (toutes les 30 secondes, voir main.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deposit import Deposit
from app.services.jessikapay import JessiKaPayError, jessikapay_service
from app.services.wallet_service import (
    DuplicateOperationError,
    WalletService,
    WalletServiceError,
)

logger = logging.getLogger("nexmarket.deposits")

PAID_STATUSES = {"paid", "completed", "success", "successful"}
FAILED_STATUSES = {"failed", "expired", "cancelled", "canceled", "rejected"}
FINAL_STATUSES = {"paid", "failed", "expired", "cancelled", "rejected", "amount_mismatch"}


def _money(value) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


async def sync_deposit(db: AsyncSession, deposit_id: int) -> str:
    """
    Interroge JessiKaPay et crédite le wallet si le dépôt est payé.
    Renvoie le statut du dépôt après vérification. Idempotent.
    """

    deposit = (
        await db.execute(
            select(Deposit).where(Deposit.id == deposit_id)
        )
    ).scalar_one_or_none()

    if deposit is None:
        return "unknown"

    if deposit.status in FINAL_STATUSES:
        return deposit.status

    try:
        response = await jessikapay_service.get_deposit(
            deposit.jessikapay_request_id
        )
    except JessiKaPayError as exc:
        # Prestataire indisponible : on réessaiera au prochain passage.
        logger.warning("Dépôt %s : vérification impossible : %s", deposit.reference, exc)
        return deposit.status

    if not isinstance(response, dict):
        return deposit.status

    provider_status = str(response.get("status") or "").lower()

    # ---------------------------------------------------------
    # Échec / expiration
    # ---------------------------------------------------------
    if provider_status in FAILED_STATUSES:
        deposit.status = (
            "expired" if provider_status == "expired" else "failed"
        )
        deposit.failure_reason = (
            response.get("message")
            or response.get("reason")
            or f"Dépôt {provider_status}."
        )
        await db.commit()
        return deposit.status

    if provider_status not in PAID_STATUSES:
        return deposit.status

    # ---------------------------------------------------------
    # Payé : verrou de ligne, contrôle du montant, crédit idempotent
    # ---------------------------------------------------------
    deposit = (
        await db.execute(
            select(Deposit)
            .where(Deposit.id == deposit_id)
            .with_for_update()
        )
    ).scalar_one()

    if deposit.status == "paid":
        return "paid"

    expected = _money(deposit.amount)
    reported = _money(response.get("amount")) if response.get("amount") is not None else None

    # On ne crédite jamais un montant différent de celui demandé.
    if reported is not None and reported != expected:
        deposit.status = "amount_mismatch"
        deposit.failure_reason = (
            f"Montant incohérent : attendu {expected}, reçu {reported}."
        )
        await db.commit()
        logger.error("Dépôt %s : %s", deposit.reference, deposit.failure_reason)
        return deposit.status

    try:
        await WalletService(db).credit(
            user_id=deposit.user_id,
            amount=expected,
            reference=deposit.reference,
            operation_type="deposit",
            provider_reference=deposit.jessikapay_request_id,
            description="Dépôt confirmé par JessiKaPay",
        )
    except DuplicateOperationError:
        pass  # déjà crédité lors d'un passage interrompu
    except WalletServiceError as exc:
        logger.error("Dépôt %s : crédit impossible : %s", deposit.reference, exc)
        return deposit.status

    deposit.status = "paid"
    deposit.paid_at = datetime.utcnow()
    await db.commit()

    return "paid"


async def sync_pending_deposits(session_factory, *, max_age_hours: int = 48, limit: int = 50) -> int:
    """Tâche de fond : vérifie les dépôts encore en attente."""

    since = datetime.utcnow() - timedelta(hours=max_age_hours)

    async with session_factory() as db:
        ids = (
            await db.execute(
                select(Deposit.id)
                .where(
                    Deposit.status.notin_(FINAL_STATUSES),
                    Deposit.created_at > since,
                )
                .order_by(Deposit.created_at)
                .limit(limit)
            )
        ).scalars().all()

    paid = 0

    for deposit_id in ids:
        try:
            async with session_factory() as db:
                if await sync_deposit(db, deposit_id) == "paid":
                    paid += 1
        except Exception:
            logger.exception("Dépôt %s : erreur de synchronisation", deposit_id)

    return paid
