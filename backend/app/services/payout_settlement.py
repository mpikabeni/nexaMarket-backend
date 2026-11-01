"""
Finalisation des retraits SANS webhook.

Les fonds d'un retrait sont BLOQUÉS dans le wallet dès la demande. Une fois
le payout accepté par JessiKaPay, ils sont consommés (retrait terminé) ;
s'il est refusé, ils sont rendus. Un retrait au statut inconnu (timeout)
reste « processing » jusqu'à décision d'un administrateur.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.withdrawal import Withdrawal
from app.services.wallet_service import (
    DuplicateOperationError,
    WalletService,
)

FAILED_STATUSES = {"failed", "rejected", "cancelled", "canceled", "error"}
PENDING_STATUSES = {"pending", "processing", "queued", "in_progress"}


async def complete_withdrawal(db: AsyncSession, withdrawal: Withdrawal) -> None:
    """Consomme les fonds bloqués : le retrait est terminé."""

    try:
        await WalletService(db).consume_blocked(
            user_id=withdrawal.user_id,
            amount=Decimal(str(withdrawal.amount)),
            reference=f"{withdrawal.reference}-CONSUME",
            description="Retrait JessiKaPay effectué",
        )
    except DuplicateOperationError:
        pass  # déjà consommé lors d'un passage interrompu

    withdrawal.status = "completed"
    withdrawal.completed_at = datetime.utcnow()

    await db.commit()


async def fail_withdrawal(
    db: AsyncSession,
    withdrawal: Withdrawal,
    reason: str,
) -> None:
    """Rend les fonds bloqués à l'utilisateur : le retrait a échoué."""

    try:
        await WalletService(db).release_blocked(
            user_id=withdrawal.user_id,
            amount=Decimal(str(withdrawal.amount)),
            reference=f"{withdrawal.reference}-RELEASE",
            description="Libération des fonds : retrait non effectué",
        )
    except DuplicateOperationError:
        pass

    withdrawal.status = "failed"
    withdrawal.failure_reason = reason

    await db.commit()
