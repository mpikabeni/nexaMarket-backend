"""
Versement AUTOMATIQUE au vendeur après libération des fonds par l'admin.

Quand l'admin libère l'argent, le wallet du vendeur est crédité (prix - commission).
Si l'annonce contient son compte Mobile Money (pays, réseau, numéro), cette tâche de
fond lui envoie aussitôt le montant par MoneyFusion. Sans compte enregistré, ou en
cas d'échec, l'argent reste dans son wallet et il peut le retirer à la main.

Sécurité : `seller_payout_started_at` est posé AVANT l'appel (jamais deux envois) ;
un statut incertain garde les fonds bloqués pour vérification par un admin.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select

from app.config import settings
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.services import money_notifications
from app.services.jessikapay import jessikapay_service
from app.services.moneyfusion import MoneyFusionError
from app.services.payout_settlement import fail_withdrawal
from app.services.wallet_service import WalletService, WalletServiceError

logger = logging.getLogger("nexmarket.seller_payout")


def _webhook_url() -> str:
    base = (settings.PUBLIC_URL or "").strip().rstrip("/")
    secret = (settings.MONEYFUSION_WEBHOOK_SECRET or "").strip()

    return f"{base}/webhooks/moneyfusion/{secret}" if base and secret else ""


async def auto_payout_sellers(session_factory, *, limit: int = 20) -> int:
    async with session_factory() as db:
        ids = (
            await db.execute(
                select(Transaction.id)
                .where(
                    Transaction.seller_paid_at.is_not(None),
                    Transaction.seller_payout_started_at.is_(None),
                    Transaction.currency == "XAF",
                )
                .order_by(Transaction.id)
                .limit(limit)
            )
        ).scalars().all()

    sent = 0

    for transaction_id in ids:
        try:
            if await _payout_one(session_factory, transaction_id):
                sent += 1
        except Exception:
            logger.exception("Versement vendeur %s : erreur inattendue", transaction_id)

    return sent


async def _payout_one(session_factory, transaction_id: int) -> bool:
    async with session_factory() as db:
        tx = (
            await db.execute(
                select(Transaction)
                .where(Transaction.id == transaction_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

        if tx is None or tx.seller_payout_started_at is not None:
            return False

        # Marqué AVANT l'appel externe : jamais deux versements pour la même vente.
        tx.seller_payout_started_at = datetime.utcnow()
        await db.commit()

        listing = (
            await db.execute(select(Listing).where(Listing.id == tx.listing_id))
        ).scalar_one_or_none()

        if not (listing and listing.payout_phone):
            return False  # pas de numéro JP : l'argent reste dans le wallet

        amount = Decimal(str(tx.seller_amount)).to_integral_value(rounding=ROUND_DOWN)

        if amount <= 0:
            logger.warning("Versement vendeur %s : montant nul", tx.reference)
            return False

        user = (await db.execute(select(User).where(User.id == tx.seller_id))).scalar_one()
        reference = f"WD-AUTO-{tx.reference}"[:100]

        try:
            await WalletService(db).block(
                user_id=user.id,
                amount=amount,
                reference=reference,
                description="Fonds bloqués pour versement automatique de la vente",
            )
        except WalletServiceError as exc:
            logger.warning("Versement vendeur %s : blocage impossible : %s", tx.reference, exc)
            return False

        withdrawal = Withdrawal(
            user_id=user.id,
            reference=reference,
            amount=amount,
            currency="XAF",
            payout_country="JP",
            payout_method="jessikapay",
            payout_phone=listing.payout_phone,
            payout_currency="XAF",
            payout_amount=int(amount),
            status="pending",
        )
        db.add(withdrawal)
        await db.commit()
        await db.refresh(withdrawal)

        try:
            response = await jessikapay_service.payout(
                jp_number=listing.payout_phone,
                amount=int(amount),
                reference=reference,
                description="Vente de canal NexMarket",
            )
        except MoneyFusionError as exc:
            if exc.ambiguous:
                # Peut-être déjà payé : fonds gardés bloqués, un admin vérifie.
                withdrawal.status = "processing"
                withdrawal.processed_at = datetime.utcnow()
                withdrawal.failure_reason = f"Statut inconnu, à vérifier : {exc}"
                await db.commit()
                await money_notifications.withdrawal_processing(db, withdrawal, needs_admin=True)
                return False

            await fail_withdrawal(db, withdrawal, str(exc))
            await money_notifications.withdrawal_failed(db, withdrawal, str(exc))
            return False

        withdrawal.jessikapay_transaction_id = response["token"]
        withdrawal.status = "processing"
        withdrawal.processed_at = datetime.utcnow()
        await db.commit()
        await money_notifications.withdrawal_processing(db, withdrawal, needs_admin=False)
        return True
