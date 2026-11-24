"""
Vérification des dépôts MoneyFusion.

NexMarket interroge lui-même le statut du paiement
(GET /paiementNotif/{token}) :
- à la demande de l'utilisateur (POST /deposits/{id}/check) ;
- en tâche de fond (toutes les 30 secondes, voir main.py) ;
- quand un webhook arrive (il ne fait que déclencher cette vérification).
Le wallet n'est JAMAIS crédité d'après le contenu d'un webhook.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.deposit import Deposit
from app.services import money_notifications
from app.services.jessikapay import jessikapay_service
from app.services.moneyfusion import MoneyFusionError
from app.services.wallet_service import (
    DuplicateOperationError,
    WalletService,
    WalletServiceError,
)

logger = logging.getLogger("nexmarket.deposits")

# Statuts normalisés par app/services/moneyfusion.py : paid / pending / failed /
# unknown. Seul « paid » prouve que l'argent est réellement reçu.
PAID_STATUSES = {"paid"}
FAILED_STATUSES = {"failed", "expired", "cancelled", "rejected"}
FINAL_STATUSES = {"paid", "failed", "expired", "cancelled", "rejected", "amount_mismatch"}


# Statuts « en cours » normaux : inutile de les journaliser à chaque passage.
WAITING_STATUSES = {"", "pending", "unknown", "reviewing", "awaiting_payment"}


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


async def _needs_attention(db, deposit, reason: str) -> None:
    """Dépôt PAYÉ chez MoneyFusion mais pas crédité : on garde la raison et on
    prévient les admins dans le bot (une seule fois par raison)."""

    if deposit.failure_reason == reason:
        return
    deposit.failure_reason = reason
    await db.commit()
    logger.error("Dépôt %s payé mais non crédité : %s", deposit.reference, reason)
    await money_notifications.deposit_attention(db, deposit, reason)


def split_deposit(amount) -> tuple[Decimal, Decimal]:
    """(frais estimés, montant NET estimé) en XAF entiers.

    ESTIMATION affichée avant le paiement. Au moment du crédit, le montant
    réellement crédité est celui que MoneyFusion confirme (champ « Montant »).
    Net arrondi vers le bas : jamais plus que ce que NexMarket reçoit.
    """

    total = Decimal(str(amount))
    rate = Decimal(str(settings.JESSIKAPAY_COMMISSION_RATE))
    net = (total * (Decimal(1) - rate)).to_integral_value(rounding=ROUND_FLOOR)
    return total - net, net


def total_to_pay(amount) -> Decimal:
    """L'utilisateur paie exactement le montant choisi ; les frais sont déduits."""

    return Decimal(str(amount))


async def sync_deposit(db: AsyncSession, deposit_id: int, *, force: bool = False) -> str:
    """
    Interroge MoneyFusion et crédite le wallet si le dépôt est payé.
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
        response = await jessikapay_service.get_payment_status(
            deposit.jessikapay_request_id
        )
    except MoneyFusionError as exc:
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
            "Dépôt %s : statut MoneyFusion non reconnu %r — réponse brute : %s",
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
        # Étapes intermédiaires de MoneyFusion : on les garde pour savoir où
        # en est l'utilisateur (lien pas ouvert / revue / paiement en cours).
        if provider_status in {"pending", "reviewing", "awaiting_payment"} \
                and deposit.status != provider_status:
            deposit.status = provider_status
            await db.commit()
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

    # La référence renvoyée par MoneyFusion doit être la nôtre (le jeton est
    # propre à ce dépôt : une différence signale une anomalie).
    provider_reference = response.get("reference")

    if provider_reference and provider_reference != deposit.reference:
        deposit.status = "amount_mismatch"
        await _needs_attention(
            db,
            deposit,
            f"Référence incohérente : MoneyFusion indique {provider_reference}, "
            f"attendu {deposit.reference}.",
        )
        return deposit.status

    # Montant NET : JessiKaPay crédite NexMarket du montant demandé moins 6 %.
    # Le champ « amount » de son statut est le montant DEMANDÉ : on ne s'en sert
    # pas pour créditer (sinon 6 % de trop).
    deposit.commission_amount, deposit.net_amount_credited = split_deposit(expected)
    net = _money(deposit.net_amount_credited)

    if net is None or net <= 0:
        await _needs_attention(db, deposit, "Montant net nul, aucun crédit possible.")
        return deposit.status

    try:
        await WalletService(db).credit(
            user_id=deposit.user_id,
            amount=net,
            reference=deposit.reference,
            operation_type="deposit",
            provider_reference=deposit.jessikapay_request_id,
            description="Paiement confirmé (net après frais)",
        )
    except DuplicateOperationError:
        pass  # déjà crédité lors d'un passage interrompu
    except WalletServiceError as exc:
        logger.error("Dépôt %s : crédit impossible : %s", deposit.reference, exc)
        await _needs_attention(db, deposit, f"Crédit du wallet impossible : {exc}")
        return deposit.status

    deposit.status = "paid"
    deposit.failure_reason = None
    deposit.paid_at = datetime.utcnow()
    await db.commit()

    # Utilisateur + MoneyFusion ont confirmé : le bot prévient, sans
    # aucune validation manuelle.
    if deposit.purpose == "purchase" and deposit.listing_id:
        await _finish_purchase(db, deposit)
    else:
        await money_notifications.deposit_paid(db, deposit)

    return "paid"


async def _finish_purchase(db, deposit) -> None:
    """Paiement direct confirmé : crée l'achat et bloque les fonds (escrow habituel).

    Si l'achat est impossible (annonce vendue entre-temps...), l'argent reste
    DISPONIBLE dans le wallet de l'acheteur : rien n'est perdu.
    """

    from app.services.notification_service import notify_user_id
    from app.services.transaction_service import TransactionService

    # Valeurs lues AVANT l'achat : après un rollback, l'objet est invalidé.
    user_id = deposit.user_id
    listing_id = deposit.listing_id
    reference = deposit.reference
    net_credited = deposit.net_amount_credited

    try:
        transaction = await TransactionService(db).purchase(
            buyer_id=user_id,
            listing_id=listing_id,
        )
        message = (
            "✅ Paiement confirmé\n\n"
            f"Tes fonds sont bloqués en sécurité pour la transaction {transaction.reference}. "
            "Un administrateur va prendre en charge ton achat."
        )
    except Exception as exc:
        await db.rollback()
        logger.warning("Achat direct %s impossible : %s", reference, exc)

        from app.models.listing import Listing

        listing = (
            await db.execute(select(Listing).where(Listing.id == listing_id))
        ).scalar_one_or_none()
        net = _money(net_credited) if net_credited is not None else None
        short = bool(
            listing is not None and net is not None and net < _money(listing.price)
        )

        if short:
            # Les frais réels de MoneyFusion dépassent l'estimation : achat bloqué.
            message = (
                "✅ Paiement reçu, mais l'achat n'a pas pu être créé : "
                "le montant reçu après frais est inférieur au prix du canal.\n\n"
                "Ton argent est disponible dans ton solde NexMarket. "
                "Aucun montant n'est perdu."
            )
            deposit = (
                await db.execute(select(Deposit).where(Deposit.reference == reference))
            ).scalar_one()
            await _needs_attention(
                db,
                deposit,
                f"Achat direct bloqué : net reçu {net} XAF < prix {listing.price} XAF. "
                "Les frais MoneyFusion dépassent MONEYFUSION_DEPOSIT_FEE_RATE : "
                "augmentez ce taux.",
            )
        else:
            message = (
                "✅ Paiement reçu, mais l'achat n'a pas pu être créé "
                "(annonce déjà vendue ou indisponible).\n\n"
                "Ton argent est disponible dans ton solde NexMarket."
            )

    try:
        await notify_user_id(db, user_id, message)
    except Exception:
        logger.exception("Notification d'achat non envoyée")


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
    MoneyFusion : le wallet n'est crédité que si MoneyFusion confirme le
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
