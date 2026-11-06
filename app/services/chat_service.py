"""
Messagerie d'une transaction : acheteur + vendeur + administrateur.

Un seul fil de discussion partagé. Chaque message écrit (Mini App,
console admin ou bot) est enregistré puis relayé par le bot aux autres
participants, avec un bouton « Répondre » et un bouton pour continuer
dans la Mini App.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.listing import Listing
from app.models.message import Message
from app.models.transaction import Transaction
from app.models.user import User
from app.services.notification_service import (
    admin_chat_ids,
    notify_telegram,
)

logger = logging.getLogger("nexmarket.chat")

ROLE_LABELS = {
    "buyer": "Acheteur",
    "seller": "Vendeur",
    "admin": "Admin NexMarket",
    "system": "NexMarket",
}

MAX_LENGTH = 5000


def _frontend_url() -> str:
    return (settings.FRONTEND_URL or "").rstrip("/")


def role_for(transaction: Transaction, user: User) -> str | None:
    if user.is_admin:
        return "admin"

    if transaction.buyer_id == user.id:
        return "buyer"

    if transaction.seller_id == user.id:
        return "seller"

    return None


def display_name(user: User | None) -> str:
    if user is None:
        return "Utilisateur"

    if user.first_name:
        return user.first_name

    if user.username:
        return f"@{user.username}"

    return user.nexa_id or f"#{user.id}"


def chat_markup(transaction_id: int, *, for_admin: bool):
    """Boutons sous chaque message relayé par le bot."""

    from telegram import (
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        WebAppInfo,
    )

    rows = [
        [
            InlineKeyboardButton(
                "↩️ Répondre",
                callback_data=f"chat:{transaction_id}",
            )
        ]
    ]

    url = _frontend_url()

    if url:
        if for_admin:
            rows.append(
                [InlineKeyboardButton("🖥️ Ouvrir la console", url=f"{url}/admin/")]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        "📱 Continuer dans la Mini App",
                        web_app=WebAppInfo(url=url),
                    )
                ]
            )

    return InlineKeyboardMarkup(rows)


async def _admin_targets(db: AsyncSession, transaction: Transaction) -> list[int]:
    """Admin en charge s'il existe, sinon tous les administrateurs."""

    if transaction.assigned_admin_id:
        telegram_id = (
            await db.execute(
                select(User.telegram_id).where(
                    User.id == transaction.assigned_admin_id
                )
            )
        ).scalar_one_or_none()

        if telegram_id:
            return [int(telegram_id)]

    return await admin_chat_ids(db)


async def post_message(
    db: AsyncSession,
    transaction: Transaction,
    user: User,
    content: str | None,
    *,
    message_type: str = "text",
    attachment_url: str | None = None,
    attachment_file_id: str | None = None,
) -> Message:
    """Enregistre le message puis le relaie par le bot."""

    role = role_for(transaction, user)

    if role is None:
        raise PermissionError("Expéditeur non autorisé.")

    # Le premier admin qui écrit prend la transaction en charge.
    if role == "admin" and not transaction.assigned_admin_id:
        transaction.assigned_admin_id = user.id

    message = Message(
        transaction_id=transaction.id,
        sender_id=user.id,
        sender_telegram_id=user.telegram_id,
        sender_role=role,
        content=content or None,
        message_type=message_type,
        attachment_url=attachment_url,
        attachment_file_id=attachment_file_id,
        is_system_message=False,
        is_read=False,
    )

    db.add(message)
    await db.commit()
    await db.refresh(message)

    try:
        await relay_message(db, transaction, message, user)
    except Exception as exc:  # noqa: BLE001
        # Le message est enregistré : un relais raté ne doit rien casser.
        logger.warning("Relais du message %s impossible : %s", message.id, exc)

    return message


async def relay_message(
    db: AsyncSession,
    transaction: Transaction,
    message: Message,
    sender: User,
) -> None:
    text_body = message.content or "📎 Pièce jointe"
    role = message.sender_role

    header = (
        f"💬 Discussion #{transaction.id} · {transaction.reference}\n"
        f"{ROLE_LABELS.get(role, role)} — {display_name(sender)} :\n\n"
    )

    text = header + text_body

    # destinataires : (telegram_id, is_admin)
    targets: dict[int, bool] = {}

    for user_id in (transaction.buyer_id, transaction.seller_id):
        if user_id == sender.id:
            continue

        telegram_id = (
            await db.execute(
                select(User.telegram_id).where(User.id == user_id)
            )
        ).scalar_one_or_none()

        if telegram_id:
            targets[int(telegram_id)] = False

    if role != "admin":
        for chat_id in await _admin_targets(db, transaction):
            targets[int(chat_id)] = True

    targets.pop(int(sender.telegram_id), None)

    for telegram_id, is_admin in targets.items():
        notify_telegram(
            telegram_id,
            text,
            chat_markup(transaction.id, for_admin=is_admin),
        )


async def open_transaction_chat(
    db: AsyncSession,
    transaction: Transaction,
) -> None:
    """
    Appelée quand l'achat est payé (fonds bloqués) : ouvre la discussion
    entre l'acheteur, le vendeur et l'administrateur, et prévient tout
    le monde dans le bot.
    """

    listing_title = (
        await db.execute(
            select(Listing.title).where(Listing.id == transaction.listing_id)
        )
    ).scalar_one_or_none() or "Canal"

    users = {
        u.id: u
        for u in (
            await db.execute(
                select(User).where(
                    User.id.in_(
                        {transaction.buyer_id, transaction.seller_id}
                    )
                )
            )
        ).scalars()
    }

    buyer = users.get(transaction.buyer_id)
    seller = users.get(transaction.seller_id)

    amount = f"{int(round(float(transaction.total_buyer_amount))):,}".replace(
        ",", " "
    )
    price = f"{amount} {transaction.currency}"

    # Message système en tête de discussion.
    if buyer is not None:
        db.add(
            Message(
                transaction_id=transaction.id,
                sender_id=buyer.id,
                sender_telegram_id=buyer.telegram_id,
                sender_role="system",
                content=(
                    "🔒 Paiement reçu : les fonds de l'acheteur sont "
                    "bloqués par NexMarket.\n"
                    "Cette discussion réunit l'acheteur, le vendeur et "
                    "l'administrateur en charge du transfert du canal."
                ),
                message_type="system",
                is_system_message=True,
                is_read=True,
            )
        )
        await db.commit()

    ref = f"Discussion #{transaction.id} · {transaction.reference}"

    if buyer is not None:
        notify_telegram(
            buyer.telegram_id,
            f"🛒 Achat confirmé — {listing_title}\n\n"
            f"💰 {price} sont bloqués en sécurité. Un administrateur NexMarket "
            "va organiser le transfert du canal avec le vendeur.\n\n"
            f"{ref}\n"
            "Tu peux écrire à l'administrateur et au vendeur ici (bouton "
            "« Répondre ») ou dans la Mini App.",
            chat_markup(transaction.id, for_admin=False),
        )

    if seller is not None:
        notify_telegram(
            seller.telegram_id,
            f"💰 Nouvelle vente — {listing_title}\n\n"
            f"L'acheteur a payé {price} : les fonds sont bloqués en "
            "sécurité. Un administrateur NexMarket va te contacter pour "
            "le transfert du canal.\n\n"
            f"{ref}\n"
            "Réponds ici (bouton « Répondre ») ou dans la Mini App.",
            chat_markup(transaction.id, for_admin=False),
        )

    admin_text = (
        f"🛒 Nouvel achat à traiter — {listing_title}\n\n"
        f"💰 {price} bloqués\n"
        f"Acheteur : {display_name(buyer)}\n"
        f"Vendeur : {display_name(seller)}\n\n"
        f"{ref}\n"
        "La discussion est ouverte : écris ici (bouton « Répondre ») ou "
        "depuis la console > Transactions."
    )

    for chat_id in await _admin_targets(db, transaction):
        notify_telegram(
            chat_id,
            admin_text,
            chat_markup(transaction.id, for_admin=True),
        )
