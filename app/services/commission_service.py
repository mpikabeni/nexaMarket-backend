"""
Versement des commissions NexMarket vers le compte JessiKaPay.

Après chaque transaction terminée, la commission (5 %) est versée sur
NEXA_JP_NUMBER via un payout JessiKaPay. Règles de sécurité :

- une seule ligne par transaction (pas de double versement) ;
- le statut « sending » est enregistré AVANT l'appel au prestataire :
  si le serveur s'arrête en plein appel, on ne renvoie jamais seul ;
- timeout / erreur 5xx = issue inconnue -> « processing » + alerte admin,
  jamais de nouvel envoi automatique ;
- refus explicite (4xx) : 5 essais maximum, puis alerte admin.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select

from app.config import settings
from app.models.platform import CommissionPayout
from app.services import money_notifications
from app.services.jessikapay import JessiKaPayError, jessikapay_service

logger = logging.getLogger("nexmarket.commissions")

MAX_ATTEMPTS = 5
FAILED_STATUSES = {"failed", "rejected", "cancelled", "canceled", "error"}


async def settle_pending_commissions(session_factory, *, limit: int = 20) -> int:
    """Verse les commissions en attente. Renvoie le nombre versé."""

    jp_number = (settings.NEXA_JP_NUMBER or "").strip()

    if not jp_number:
        return 0  # non configuré : rien n'est envoyé

    async with session_factory() as db:
        ids = (
            await db.execute(
                select(CommissionPayout.id)
                .where(
                    CommissionPayout.status == "pending",
                    CommissionPayout.attempts < MAX_ATTEMPTS,
                )
                .order_by(CommissionPayout.id)
                .limit(limit)
            )
        ).scalars().all()

    sent = 0

    for payout_id in ids:
        try:
            if await _send_one(session_factory, payout_id, jp_number):
                sent += 1
        except Exception:
            logger.exception("Commission %s : erreur inattendue", payout_id)

    return sent


async def _send_one(session_factory, payout_id: int, jp_number: str) -> bool:
    async with session_factory() as db:
        row = (
            await db.execute(
                select(CommissionPayout)
                .where(CommissionPayout.id == payout_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

        if row is None or row.status != "pending":
            return False

        # Verrouillage logique AVANT l'appel externe.
        row.status = "sending"
        row.attempts = (row.attempts or 0) + 1
        await db.commit()

        # L'API JessiKaPay n'accepte que des FCFA entiers : on verse la
        # partie entière (moins d'1 XAF reste sur le solde de l'app).
        whole = int(Decimal(row.amount).to_integral_value(rounding=ROUND_DOWN))

        if whole <= 0:
            row.status = "sent"
            row.failure_reason = "Commission inférieure à 1 XAF : rien à verser."
            await db.commit()
            return False

        payload = {
            "jp_number": jp_number,
            "amount": whole,
            "reference": row.reference,
            "description": f"Commission NexMarket {row.reference}",
        }

        try:
            response = await jessikapay_service.payout(payload)

        except JessiKaPayError as exc:
            if exc.ambiguous:
                row.status = "processing"
                row.failure_reason = f"Statut inconnu, à vérifier : {exc}"
                await db.commit()
                await money_notifications.commission_alert(db, row)
                return False

            row.status = "pending" if row.attempts < MAX_ATTEMPTS else "failed"
            row.failure_reason = str(exc)[:500]
            await db.commit()

            if row.status == "failed":
                await money_notifications.commission_alert(db, row)

            return False

        provider_status = str(
            (response or {}).get("status") or "completed"
        ).lower()

        if provider_status in FAILED_STATUSES:
            row.status = "pending" if row.attempts < MAX_ATTEMPTS else "failed"
            row.failure_reason = str(
                (response or {}).get("message")
                or (response or {}).get("reason")
                or f"Payout {provider_status}."
            )[:500]
            await db.commit()

            if row.status == "failed":
                await money_notifications.commission_alert(db, row)

            return False

        tx_id = (response or {}).get("transaction_id")
        row.jessikapay_transaction_id = str(tx_id) if tx_id else None
        row.status = "sent"
        row.failure_reason = None
        row.sent_at = datetime.utcnow()
        await db.commit()

        await money_notifications.commission_sent(db, row)
        return True
