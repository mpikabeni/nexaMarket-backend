"""
Suivi des retraits MoneyFusion (payout asynchrone).

À la demande, MoneyFusion répond seulement « accepté » avec un jeton (tokenPay).
Le résultat réel arrive plus tard : ce module relit le statut auprès de l'API
(GET /api/v1/payout/check-status/{token}) :

- success  -> le retrait est terminé : les fonds bloqués sont consommés ;
- failed   -> le retrait a échoué : les fonds sont rendus à l'utilisateur ;
- pending / inconnu -> on ne touche à rien, on réessaiera.

Jamais de décision à partir du contenu d'un webhook (non signé) : le webhook ne
fait que déclencher cette relecture.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from app.models.platform import CommissionPayout
from app.models.withdrawal import Withdrawal
from app.services import money_notifications
from app.services.commission_service import MAX_ATTEMPTS
from app.services.jessikapay import jessikapay_service
from app.services.moneyfusion import MoneyFusionError
from app.services.payout_settlement import complete_withdrawal, fail_withdrawal

logger = logging.getLogger("nexmarket.payouts")


async def sync_withdrawal(db, withdrawal_id: int) -> str:
    """Relit le statut d'un retrait « processing » et le termine ou l'annule. Idempotent."""

    withdrawal = (
        await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))
    ).scalar_one_or_none()

    if withdrawal is None:
        return "unknown"

    token = withdrawal.jessikapay_transaction_id

    if withdrawal.status != "processing" or not token:
        return withdrawal.status

    try:
        provider = await jessikapay_service.get_payout_status(token)
    except MoneyFusionError as exc:
        logger.warning("Retrait %s : vérification impossible : %s", withdrawal.reference, exc)
        return withdrawal.status

    outcome = provider.get("status")

    if outcome not in ("completed", "failed"):
        return withdrawal.status

    # Verrou + relecture : un autre passage a pu terminer le retrait entre-temps.
    withdrawal = (
        await db.execute(
            select(Withdrawal)
            .where(Withdrawal.id == withdrawal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    if withdrawal.status != "processing":
        return withdrawal.status

    if outcome == "completed":
        await complete_withdrawal(db, withdrawal)
        await money_notifications.withdrawal_completed(db, withdrawal)
        logger.info("Retrait %s terminé (MoneyFusion)", withdrawal.reference)
    else:
        reason = "Le retrait a échoué chez MoneyFusion (numéro, réseau ou solde)."
        await fail_withdrawal(db, withdrawal, reason)
        await money_notifications.withdrawal_failed(db, withdrawal, reason)
        logger.info("Retrait %s échoué (MoneyFusion) : fonds rendus", withdrawal.reference)

    return withdrawal.status


async def sync_commission_payout(db, payout_id: int) -> str:
    """Même suivi pour le versement d'une commission NexMarket."""

    row = (
        await db.execute(select(CommissionPayout).where(CommissionPayout.id == payout_id))
    ).scalar_one_or_none()

    if row is None:
        return "unknown"

    token = row.jessikapay_transaction_id

    if row.status != "processing" or not token:
        return row.status

    try:
        provider = await jessikapay_service.get_payout_status(token)
    except MoneyFusionError as exc:
        logger.warning("Commission %s : vérification impossible : %s", row.reference, exc)
        return row.status

    outcome = provider.get("status")

    if outcome not in ("completed", "failed"):
        return row.status

    row = (
        await db.execute(
            select(CommissionPayout)
            .where(CommissionPayout.id == payout_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    if row.status != "processing":
        return row.status

    if outcome == "completed":
        row.status = "sent"
        row.failure_reason = None
        row.sent_at = datetime.utcnow()
        await db.commit()
        await money_notifications.commission_sent(db, row)
        return row.status

    # Échec confirmé : MoneyFusion n'a rien payé, on peut réessayer sans risque.
    row.status = "pending" if (row.attempts or 0) < MAX_ATTEMPTS else "failed"
    row.jessikapay_transaction_id = None
    row.failure_reason = "Versement refusé par MoneyFusion."
    await db.commit()

    if row.status == "failed":
        await money_notifications.commission_alert(db, row)

    return row.status


async def sync_pending_payouts(session_factory, *, limit: int = 50) -> int:
    """Tâche de fond : retraits et commissions « processing » ayant un jeton de suivi.

    Retourne le nombre d'éléments terminés ou échoués pendant ce passage.
    """

    async with session_factory() as db:
        withdrawal_ids = (
            await db.execute(
                select(Withdrawal.id)
                .where(
                    Withdrawal.status == "processing",
                    Withdrawal.jessikapay_transaction_id.is_not(None),
                )
                .order_by(Withdrawal.id)
                .limit(limit)
            )
        ).scalars().all()

        commission_ids = (
            await db.execute(
                select(CommissionPayout.id)
                .where(
                    CommissionPayout.status == "processing",
                    CommissionPayout.jessikapay_transaction_id.is_not(None),
                )
                .order_by(CommissionPayout.id)
                .limit(limit)
            )
        ).scalars().all()

    changed = 0

    for withdrawal_id in withdrawal_ids:
        try:
            async with session_factory() as db:
                if await sync_withdrawal(db, withdrawal_id) in ("completed", "failed"):
                    changed += 1
        except Exception:
            logger.exception("Retrait %s : erreur de synchronisation", withdrawal_id)

    for payout_id in commission_ids:
        try:
            async with session_factory() as db:
                if await sync_commission_payout(db, payout_id) in ("sent", "failed", "pending"):
                    changed += 1
        except Exception:
            logger.exception("Commission %s : erreur de synchronisation", payout_id)

    return changed
