"""
Versement des commissions NexMarket vers le compte Mobile Money de la plateforme.

Après chaque transaction terminée, la commission (5 %) est versée au compte
configuré (NEXA_PAYOUT_COUNTRY / NEXA_PAYOUT_METHOD / NEXA_PAYOUT_PHONE) via un
payout MoneyFusion. Règles de sécurité :

- une seule ligne par transaction (pas de double versement) ;
- le statut « sending » est enregistré AVANT l'appel au prestataire :
  si le serveur s'arrête en plein appel, on ne renvoie jamais seul ;
- demande acceptée -> « processing » avec le jeton de suivi ; la confirmation
  (versée / échec) est relue plus tard par app/services/payout_sync.py ;
- timeout / erreur 5xx / réponse sans jeton = issue inconnue -> « processing »
  SANS jeton + alerte admin, jamais de nouvel envoi automatique ;
- refus explicite : 5 essais maximum, puis alerte admin.
"""

from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select

from app.config import settings
from app.models.platform import CommissionPayout
from app.services import money_notifications
from app.services.countries import local_phone
from app.services.jessikapay import jessikapay_service
from app.services.moneyfusion import MoneyFusionError

logger = logging.getLogger("nexmarket.commissions")

MAX_ATTEMPTS = 5


def _webhook_url() -> str:
    base = (settings.PUBLIC_URL or "").strip().rstrip("/")
    secret = (settings.MONEYFUSION_WEBHOOK_SECRET or "").strip()

    return f"{base}/webhooks/moneyfusion/{secret}" if base and secret else ""


async def _target() -> dict | None:
    """Numéro JP de NexMarket (NEXA_JP_NUMBER), ou None si non configuré."""

    from app.services.jessikapay import normalize_jp

    jp = normalize_jp(settings.NEXA_JP_NUMBER)

    if not jp:
        return None  # non configuré : rien n'est envoyé

    return {"jp": jp}


async def settle_pending_commissions(session_factory, *, limit: int = 20) -> int:
    """Soumet les commissions en attente. Renvoie le nombre de versements demandés."""

    if not (settings.NEXA_PAYOUT_COUNTRY and settings.NEXA_PAYOUT_METHOD and settings.NEXA_PAYOUT_PHONE):
        return 0

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

    if not ids:
        return 0

    target = await _target()

    if target is None:
        return 0

    sent = 0

    for payout_id in ids:
        try:
            if await _send_one(session_factory, payout_id, target):
                sent += 1
        except Exception:
            logger.exception("Commission %s : erreur inattendue", payout_id)

    return sent


async def _send_one(session_factory, payout_id: int, target: dict) -> bool:
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

        # Montants entiers uniquement : moins d'1 XAF reste sur le solde de l'app.
        whole = int(Decimal(row.amount).to_integral_value(rounding=ROUND_DOWN))
        if whole <= 0:
            row.status = "sent"
            row.failure_reason = "Commission inférieure à 1 unité : rien à verser."
            await db.commit()
            return False

        try:
            response = await jessikapay_service.payout(
                jp_number=target["jp"],
                amount=whole,
                reference=row.reference,
                description="Commission NexMarket",
            )

        except MoneyFusionError as exc:
            if exc.ambiguous:
                row.status = "processing"  # sans jeton : un admin vérifie
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

        # Demande acceptée : la confirmation arrive plus tard (payout_sync).
        row.jessikapay_transaction_id = response["token"]
        row.status = "processing"
        row.failure_reason = None
        await db.commit()
        return True
