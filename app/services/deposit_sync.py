"""
Vérification des dépôts SANS webhook.

JessiKaPay n'appelle plus NexMarket : c'est NexMarket qui interroge le
point d'état du prestataire (GET /external/v1/deposit-request/{id}/status)
- à la demande de l'utilisateur (POST /deposits/{id}/check) ;
- en tâche de fond (toutes les 30 secondes, voir main.py).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.deposit import Deposit
from app.services import money_notifications
from app.services.jessikapay import JessiKaPayError, jessikapay_service
from app.services.wallet_service import (
    DuplicateOperationError,
    WalletService,
    WalletServiceError,
)

logger = logging.getLogger("nexmarket.deposits")

# Statuts qui prouvent que l'argent est réellement reçu. Liste volontairement
# stricte (argent réel) : des mots vagues comme « approved » ou « validated »
# peuvent désigner une étape intermédiaire. Si JessiKaPay utilise un autre mot
# pour « payé », ajoutez-le dans la variable Render JESSIKAPAY_PAID_STATUSES
# (séparés par des virgules) ; le statut brut reçu est écrit dans les logs.
PAID_STATUSES = {"paid", "completed", "success", "successful", "succeeded"} | {
    item.strip().lower()
    for item in os.environ.get("JESSIKAPAY_PAID_STATUSES", "").split(",")
    if item.strip()
}
FAILED_STATUSES = {"failed", "failure", "expired", "cancelled", "canceled", "rejected", "declined", "refused"}
FINAL_STATUSES = {"paid", "failed", "expired", "cancelled", "rejected", "amount_mismatch"}


# Statuts « en cours » normaux : inutile de les journaliser à chaque passage.
WAITING_STATUSES = {"", "pending", "waiting", "created", "processing", "initiated", "in_progress", "awaiting_payment", "unpaid"}


def _unwrap(response: dict) -> dict:
    """Certaines API enveloppent la réponse dans « data »."""

    inner = response.get("data")

    if isinstance(inner, dict) and ("status" in inner or "state" in inner):
        return {**response, **inner}

    return response


def _provider_status(response: dict) -> str:
    for key in ("status", "state", "payment_status", "request_status"):
        value = response.get(key)
        if value:
            return str(value).strip().lower()

    return ""


def _money(value) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def split_deposit(amount) -> tuple[Decimal, Decimal]:
    """(commission JessiKaPay, montant NET crédité au wallet) en XAF entiers.

    JessiKaPay prélève 6 % sur ce que NexMarket reçoit : le wallet n'est
    crédité que du net. Arrondi toujours en faveur de la solvabilité (le net
    est arrondi vers le bas : jamais plus que ce que NexMarket reçoit).
    """

    total = Decimal(str(amount))
    rate = Decimal(str(settings.JESSIKAPAY_DEPOSIT_COMMISSION_RATE))
    net = (total * (Decimal(1) - rate)).to_integral_value(rounding=ROUND_FLOOR)
    return total - net, net


def total_to_pay(amount) -> Decimal:
    """Montant approximatif payé par l'utilisateur (frais Mobile Money +3 %)."""

    rate = Decimal(str(settings.JESSIKAPAY_USER_FEE_RATE))
    return (Decimal(str(amount)) * (Decimal(1) + rate)).to_integral_value(rounding=ROUND_CEILING)


async def sync_deposit(db: AsyncSession, deposit_id: int, *, force: bool = False) -> str:
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

    if deposit.status == "paid":
        return "paid"

    # force=True (admin) : on revérifie aussi un dépôt classé en échec,
    # expiré ou « montant incohérent ».
    if deposit.status in FINAL_STATUSES and not force:
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

    response = _unwrap(response)
    provider_status = _provider_status(response)

    if provider_status not in PAID_STATUSES and provider_status not in FAILED_STATUSES \
            and provider_status not in WAITING_STATUSES:
        logger.warning(
            "Dépôt %s : statut JessiKaPay non reconnu %r — réponse brute : %s",
            deposit.reference, provider_status, response,
        )

    # ---------------------------------------------------------
    # Échec / expiration
    # ---------------------------------------------------------
    if provider_status in FAILED_STATUSES:
        previous_status = deposit.status
        deposit.status = (
            "expired" if provider_status == "expired" else "failed"
        )
        deposit.failure_reason = (
            response.get("message")
            or response.get("reason")
            or f"Dépôt {provider_status}."
        )
        await db.commit()

        # Prévenu une seule fois (pas lors d'une revérification admin).
        if previous_status not in FINAL_STATUSES:
            await money_notifications.deposit_failed(db, deposit)

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

    # On ne crédite jamais MOINS que le montant demandé. Un montant
    # supérieur (frais ajoutés par l'opérateur) est accepté : on crédite
    # exactement le montant demandé.
    if reported is not None and expected is not None and reported < expected:
        deposit.status = "amount_mismatch"
        deposit.failure_reason = (
            f"Montant incohérent : attendu {expected}, reçu {reported}."
        )
        await db.commit()
        logger.error("Dépôt %s : %s", deposit.reference, deposit.failure_reason)
        return deposit.status

    # Montant NET à créditer (après la commission JessiKaPay de 6 %).
    if deposit.net_amount_credited is None or deposit.commission_amount is None:
        deposit.commission_amount, deposit.net_amount_credited = split_deposit(expected)

    net = _money(deposit.net_amount_credited)

    if net is None or net <= 0:
        logger.error("Dépôt %s : montant net nul, aucun crédit.", deposit.reference)
        return deposit.status

    try:
        await WalletService(db).credit(
            user_id=deposit.user_id,
            amount=net,
            reference=deposit.reference,
            operation_type="deposit",
            provider_reference=deposit.jessikapay_request_id,
            description="Dépôt confirmé par JessiKaPay (net après frais)",
        )
    except DuplicateOperationError:
        pass  # déjà crédité lors d'un passage interrompu
    except WalletServiceError as exc:
        logger.error("Dépôt %s : crédit impossible : %s", deposit.reference, exc)
        return deposit.status

    deposit.status = "paid"
    deposit.failure_reason = None
    deposit.paid_at = datetime.utcnow()
    await db.commit()

    # Utilisateur + JessiKaPay ont confirmé : le bot prévient, sans
    # aucune validation manuelle.
    await money_notifications.deposit_paid(db, deposit)

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


async def credit_deposit_manually(db: AsyncSession, deposit_id: int, admin_id: int, note: str = "") -> str:
    """
    L'administrateur NE crédite PLUS d'argent lui-même.

    Cette fonction force seulement une nouvelle vérification auprès de
    JessiKaPay : le wallet n'est crédité que si JessiKaPay confirme le
    paiement (et pour un montant au moins égal au montant demandé).
    Sinon rien n'est crédité. Idempotent (référence unique).
    """

    deposit = (
        await db.execute(select(Deposit).where(Deposit.id == deposit_id))
    ).scalar_one_or_none()

    if deposit is None:
        return "unknown"

    logger.info(
        "Dépôt %s : revérification demandée par l'admin #%s %s",
        deposit.reference, admin_id, note,
    )

    return await sync_deposit(db, deposit_id, force=True)
