"""
Notifications du bot pour les dépôts et les retraits.

Principe : plus aucune validation manuelle. Dès que l'utilisateur a
confirmé sa demande ET que JessiKaPay a confirmé l'opération, le bot
écrit à l'utilisateur (et envoie une copie d'information aux admins).
Toutes les fonctions sont « best effort » : une notification ratée ne
casse jamais une opération d'argent.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.models.user import User
from app.services.notification_service import notify_admins, notify_user_id

logger = logging.getLogger("nexmarket.money_notify")


def fmt_amount(value, currency: str = "XAF") -> str:
    try:
        number = int(round(float(value)))
        return f"{number:,}".replace(",", " ") + f" {currency}"
    except Exception:
        return f"{value} {currency}"


async def _who(db, user_id: int) -> str:
    try:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    except Exception:
        return f"#{user_id}"

    if user is None:
        return f"#{user_id}"

    if user.username:
        return f"@{user.username} ({user.nexa_id or user.id})"

    return f"{user.first_name or 'Utilisateur'} ({user.nexa_id or user.id})"


async def _safe(coro) -> None:
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notification d'argent non envoyée : %s", exc)


# ============================================================
# DÉPÔTS
# ============================================================

async def deposit_requested(db, deposit) -> None:
    """L'utilisateur a confirmé sa demande : on attend JessiKaPay."""

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    markup = None

    if deposit.payment_link and str(deposit.payment_link).startswith("http"):
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💳 Payer maintenant", url=deposit.payment_link)]]
        )

    await _safe(
        notify_user_id(
            db,
            deposit.user_id,
            "⏳ Demande de dépôt enregistrée\n\n"
            f"Montant : {fmt_amount(deposit.amount, deposit.currency)}\n"
            f"Référence : {deposit.reference}\n\n"
            "Termine le paiement Mobile Money. Dès que JessiKaPay le "
            "confirme, ton solde est crédité automatiquement et tu es "
            "prévenu ici.",
            markup,
        )
    )


async def deposit_paid(db, deposit) -> None:
    amount = fmt_amount(deposit.amount, deposit.currency)

    await _safe(
        notify_user_id(
            db,
            deposit.user_id,
            "✅ Dépôt confirmé\n\n"
            f"Tu as confirmé le dépôt et JessiKaPay a validé le paiement.\n"
            f"💰 {amount} ont été ajoutés à ton solde NexMarket.\n\n"
            f"Référence : {deposit.reference}",
        )
    )

    await _safe(
        notify_admins(
            db,
            "💰 Dépôt confirmé automatiquement\n\n"
            f"Utilisateur : {await _who(db, deposit.user_id)}\n"
            f"Montant : {amount}\n"
            f"Référence : {deposit.reference}\n\n"
            "Aucune action requise.",
        )
    )


async def deposit_failed(db, deposit) -> None:
    label = "expiré" if deposit.status == "expired" else "échoué"

    await _safe(
        notify_user_id(
            db,
            deposit.user_id,
            f"❌ Dépôt {label}\n\n"
            f"Montant : {fmt_amount(deposit.amount, deposit.currency)}\n"
            f"Référence : {deposit.reference}\n"
            + (f"Motif : {deposit.failure_reason}\n" if deposit.failure_reason else "")
            + "\nAucun montant n'a été ajouté à ton solde. "
            "Tu peux refaire un dépôt depuis la Mini App.",
        )
    )


# ============================================================
# RETRAITS
# ============================================================

async def withdrawal_completed(db, withdrawal) -> None:
    amount = fmt_amount(withdrawal.amount, withdrawal.currency)

    await _safe(
        notify_user_id(
            db,
            withdrawal.user_id,
            "✅ Retrait effectué\n\n"
            "Tu as confirmé le retrait et JessiKaPay l'a exécuté.\n"
            f"💸 {amount} envoyés vers {withdrawal.jessikapay_jp_number}.\n\n"
            f"Référence : {withdrawal.reference}",
        )
    )

    await _safe(
        notify_admins(
            db,
            "💸 Retrait effectué automatiquement\n\n"
            f"Utilisateur : {await _who(db, withdrawal.user_id)}\n"
            f"Montant : {amount}\n"
            f"Compte : {withdrawal.jessikapay_jp_number}\n"
            f"Référence : {withdrawal.reference}\n\n"
            "Aucune action requise.",
        )
    )


async def withdrawal_failed(db, withdrawal, reason: str = "") -> None:
    await _safe(
        notify_user_id(
            db,
            withdrawal.user_id,
            "❌ Retrait non effectué\n\n"
            f"Montant : {fmt_amount(withdrawal.amount, withdrawal.currency)}\n"
            f"Référence : {withdrawal.reference}\n"
            + (f"Motif : {reason}\n" if reason else "")
            + "\nLes fonds ont été remis sur ton solde disponible.",
        )
    )


async def withdrawal_processing(db, withdrawal, *, needs_admin: bool) -> None:
    """Statut incertain : l'utilisateur est prévenu ; l'admin n'est
    alerté que si JessiKaPay n'a pas pu confirmer (cas exceptionnel)."""

    await _safe(
        notify_user_id(
            db,
            withdrawal.user_id,
            "⏳ Retrait en cours de traitement\n\n"
            f"Montant : {fmt_amount(withdrawal.amount, withdrawal.currency)}\n"
            f"Référence : {withdrawal.reference}\n\n"
            "JessiKaPay n'a pas encore confirmé. Tes fonds restent bloqués "
            "en sécurité et tu seras prévenu ici dès la confirmation.",
        )
    )

    if needs_admin:
        await _safe(
            notify_admins(
                db,
                "⚠️ Retrait à vérifier (réponse JessiKaPay incertaine)\n\n"
                f"Utilisateur : {await _who(db, withdrawal.user_id)}\n"
                f"Montant : {fmt_amount(withdrawal.amount, withdrawal.currency)}\n"
                f"Référence : {withdrawal.reference}\n\n"
                "Ouvre la console > Retraits à vérifier.",
            )
        )
