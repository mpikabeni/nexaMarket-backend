from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.models.user import User
from app.services.telegram_service import (
    TelegramService,
    get_telegram_service,
)

logger = logging.getLogger("nexmarket.notify")

_background_tasks: set[asyncio.Task] = set()


async def _send(telegram_id: int, text: str, reply_markup=None) -> None:
    try:
        await asyncio.wait_for(
            get_telegram_service().send_message(
                chat_id=telegram_id,
                text=text,
                reply_markup=reply_markup,
            ),
            timeout=10,
        )
    except Exception as exc:
        # Une notification ratée ne doit JAMAIS casser un achat.
        logger.warning(
            "Notification Telegram non envoyée (%s) : %s",
            telegram_id,
            exc,
        )


def notify_telegram(
    telegram_id: int | None,
    text: str,
    reply_markup=None,
) -> None:
    """Envoi non bloquant et sans exception (best effort)."""

    if not telegram_id:
        return

    try:
        task = asyncio.get_running_loop().create_task(
            _send(telegram_id, text, reply_markup)
        )
    except RuntimeError:
        return

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _send_attachment(telegram_id: int, file_id: str, kind: str, caption: str, reply_markup=None) -> None:
    """Renvoie une photo / un fichier image déjà connu de Telegram (file_id du même bot)."""

    try:
        bot = get_telegram_service().bot
        if kind == "document":
            coro = bot.send_document(
                chat_id=telegram_id, document=file_id, caption=caption[:1000], reply_markup=reply_markup
            )
        else:
            coro = bot.send_photo(
                chat_id=telegram_id, photo=file_id, caption=caption[:1000], reply_markup=reply_markup
            )
        await asyncio.wait_for(coro, timeout=20)
    except Exception as exc:
        logger.warning("Pièce jointe non envoyée (%s) : %s", telegram_id, exc)


def notify_telegram_attachment(
    telegram_id: int | None,
    file_id: str,
    kind: str,
    caption: str,
    reply_markup=None,
) -> None:
    """Envoi non bloquant d'une capture d'écran (best effort)."""

    if not telegram_id or not file_id:
        return

    try:
        task = asyncio.get_running_loop().create_task(
            _send_attachment(telegram_id, file_id, kind, caption, reply_markup)
        )
    except RuntimeError:
        return

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ============================================================
# NOUVELLE ANNONCE : prévenir tous les membres du bot
# ============================================================

def build_new_listing_text(listing, channel) -> str:
    """Texte brut (sans parse_mode : le titre du vendeur ne peut rien casser)."""

    title = (getattr(channel, "title", None) or getattr(listing, "title", None) or "Canal").strip()
    lines = ["🆕 Nouveau canal à vendre sur NexMarket !", "", f"📢 {title}"]

    category = (getattr(listing, "category", None) or "").strip()
    if category:
        lines.append(f"🏷 Catégorie : {category}")

    subscribers = getattr(channel, "subscriber_count", None)
    if subscribers:
        lines.append(f"👥 Abonnés : {int(subscribers):,}".replace(",", " "))

    price = getattr(listing, "price", None)
    if price is not None:
        try:
            price_text = format(price.normalize(), "f")
        except Exception:
            price_text = str(price)
        lines.append(f"💰 Prix : {price_text} {getattr(listing, 'currency', '') or ''}".rstrip())

    description = (getattr(listing, "description", None) or "").strip()
    if description:
        short = description[:180] + ("…" if len(description) > 180 else "")
        lines += ["", short]

    lines += ["", "Ouvre NexMarket pour voir l'annonce 👇"]
    return "\n".join(lines)


async def _send_to_all(bot, telegram_ids: list[int], text: str, reply_markup=None) -> tuple[int, int]:
    """Envoie à chacun avec une cadence douce (limite Telegram ≈ 30 msg/s).

    Retourne (envoyés, échecs). Un utilisateur qui a bloqué le bot compte comme échec ;
    une limite de débit (RetryAfter) fait patienter puis réessayer une fois.
    """

    from telegram.error import RetryAfter

    sent = 0
    failed = 0

    for telegram_id in telegram_ids:
        for attempt in range(2):
            try:
                await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                sent += 1
                break
            except RetryAfter as exc:
                if attempt == 0:
                    await asyncio.sleep(float(exc.retry_after) + 1)
                    continue
                failed += 1
            except Exception as exc:
                failed += 1
                logger.info("Annonce non envoyée à %s : %s", telegram_id, type(exc).__name__)
                break
        await asyncio.sleep(0.05)

    return sent, failed


async def _broadcast_new_listing(listing_id: int) -> None:
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

        from app.config import settings
        from app.db import AsyncSessionLocal
        from app.models.channel import Channel
        from app.models.listing import Listing

        async with AsyncSessionLocal() as db:
            listing = (
                await db.execute(select(Listing).where(Listing.id == listing_id))
            ).scalar_one_or_none()

            if listing is None or listing.status != "published":
                return

            channel = (
                await db.execute(select(Channel).where(Channel.id == listing.channel_id))
            ).scalar_one_or_none()

            seller_telegram_id = (
                await db.execute(select(User.telegram_id).where(User.id == listing.seller_id))
            ).scalar_one_or_none()

            recipients = [
                telegram_id
                for telegram_id in (
                    await db.execute(select(User.telegram_id).where(User.is_active.is_(True)))
                ).scalars().all()
                if telegram_id and telegram_id != seller_telegram_id  # le vendeur a déjà son message
            ]

            text = build_new_listing_text(listing, channel)

        if not recipients:
            return

        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("👀 Voir l'annonce", web_app=WebAppInfo(url=settings.FRONTEND_URL))]]
        )

        sent, failed = await _send_to_all(get_telegram_service().bot, recipients, text, markup)
        logger.info("Nouvelle annonce #%s diffusée : %s envoyés, %s échecs", listing_id, sent, failed)
    except Exception as exc:
        # Une diffusion ratée ne doit JAMAIS casser l'approbation.
        logger.warning("Diffusion de la nouvelle annonce #%s impossible : %s", listing_id, exc)


def schedule_new_listing_broadcast(listing_id: int) -> None:
    """Lance la diffusion en tâche de fond (l'admin n'attend pas l'envoi à tous)."""

    from app.config import settings

    if not settings.NOTIFY_NEW_LISTINGS:
        return

    try:
        task = asyncio.get_running_loop().create_task(_broadcast_new_listing(listing_id))
    except RuntimeError:
        return

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def notify_user_id(
    db,
    user_id: int | None,
    text: str,
    reply_markup=None,
) -> None:
    """Prévient un utilisateur à partir de son id NexMarket."""

    if not user_id:
        return

    try:
        telegram_id = (
            await db.execute(
                select(User.telegram_id).where(User.id == user_id)
            )
        ).scalar_one_or_none()
    except Exception as exc:
        logger.warning("Notification : utilisateur illisible : %s", exc)
        return

    notify_telegram(telegram_id, text, reply_markup)


async def notify_admins(db, text: str, reply_markup=None) -> None:
    """Prévient tous les administrateurs (copie d'information)."""

    for chat_id in await admin_chat_ids(db):
        notify_telegram(chat_id, text, reply_markup)


class NotificationService:
    """
    Notifications privées envoyées par le bot NexMarket.
    """

    def __init__(self, telegram_service: TelegramService):
        self.telegram = telegram_service

    async def notify_user(
        self,
        telegram_id: int,
        message: str,
    ) -> None:
        await self.telegram.send_message(
            chat_id=telegram_id,
            text=message,
        )

    # ========================================================
    # LISTING
    # ========================================================

    async def listing_submitted(
        self,
        telegram_id: int,
        listing_title: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "📋 Votre annonce a été envoyée pour vérification.\n\n"
                f"Annonce : {listing_title}\n"
                "Notre équipe va vérifier les informations avant "
                "sa publication."
            ),
        )

    async def listing_approved(
        self,
        telegram_id: int,
        listing_title: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "✅ Votre annonce a été approuvée.\n\n"
                f"Annonce : {listing_title}\n"
                "Elle peut maintenant être publiée sur NexMarket."
            ),
        )

    async def listing_rejected(
        self,
        telegram_id: int,
        listing_title: str,
        reason: str | None = None,
    ) -> None:
        message = (
            "❌ Votre annonce n'a pas été approuvée.\n\n"
            f"Annonce : {listing_title}"
        )

        if reason:
            message += f"\n\nMotif : {reason}"

        await self.notify_user(
            telegram_id,
            message,
        )

    # ========================================================
    # TRANSACTION
    # ========================================================

    async def transaction_created(
        self,
        telegram_id: int,
        reference: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "🛒 Nouvelle transaction créée.\n\n"
                f"Référence : {reference}\n"
                "La transaction est en attente de paiement."
            ),
        )

    async def payment_confirmed(
        self,
        telegram_id: int,
        reference: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "💰 Paiement confirmé.\n\n"
                f"Référence : {reference}\n"
                "Les fonds sont maintenant protégés par NexMarket."
            ),
        )

    async def admin_assigned(
        self,
        telegram_id: int,
        reference: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "👨‍💼 Un administrateur NexMarket a été assigné "
                "à votre transaction.\n\n"
                f"Référence : {reference}"
            ),
        )

    async def transfer_started(
        self,
        telegram_id: int,
        reference: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "🔄 Le transfert du canal a commencé.\n\n"
                f"Référence : {reference}\n"
                "L'équipe NexMarket vérifie maintenant le transfert."
            ),
        )

    async def protection_started(
        self,
        telegram_id: int,
        reference: str,
        protection_minutes: int,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "🛡️ La période de protection a commencé.\n\n"
                f"Référence : {reference}\n"
                f"Durée : {protection_minutes} minutes.\n\n"
                "Les fonds restent protégés pendant cette période."
            ),
        )

    async def transaction_completed(
        self,
        telegram_id: int,
        reference: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "✅ Transaction terminée.\n\n"
                f"Référence : {reference}\n"
                "La transaction NexMarket est maintenant clôturée."
            ),
        )

    # ========================================================
    # DISPUTE
    # ========================================================

    async def dispute_opened(
        self,
        telegram_id: int,
        reference: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "⚠️ Un litige a été ouvert.\n\n"
                f"Référence : {reference}\n"
                "Un administrateur NexMarket va examiner la situation."
            ),
        )

    async def dispute_resolved(
        self,
        telegram_id: int,
        reference: str,
        resolution: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "⚖️ Le litige a été traité.\n\n"
                f"Référence : {reference}\n"
                f"Décision : {resolution}"
            ),
        )

    # ========================================================
    # PAYOUT
    # ========================================================

    async def seller_paid(
        self,
        telegram_id: int,
        reference: str,
        amount: str,
        currency: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "💸 Votre paiement vendeur a été effectué.\n\n"
                f"Référence : {reference}\n"
                f"Montant : {amount} {currency}"
            ),
        )

    # ========================================================
    # REFUND
    # ========================================================

    async def refund_completed(
        self,
        telegram_id: int,
        reference: str,
        amount: str,
        currency: str,
    ) -> None:
        await self.notify_user(
            telegram_id,
            (
                "↩️ Votre remboursement a été effectué.\n\n"
                f"Référence : {reference}\n"
                f"Montant : {amount} {currency}"
            ),
        )


# ============================================================
# ADMIN : nouvelle annonce + photos de preuve
# ============================================================

async def _send_listing_proofs(chat_ids: list[int], text: str, photos: list[bytes]) -> None:
    from telegram import InputMediaPhoto

    bot = get_telegram_service().bot

    for chat_id in chat_ids:
        try:
            if not photos:
                await asyncio.wait_for(
                    bot.send_message(chat_id=chat_id, text=text[:4000]),
                    timeout=30,
                )
            elif len(photos) == 1:
                await asyncio.wait_for(
                    bot.send_photo(chat_id=chat_id, photo=photos[0], caption=text[:1000]),
                    timeout=30,
                )
            else:
                media = [
                    InputMediaPhoto(
                        media=photo,
                        caption=text[:1000] if index == 0 else None,
                    )
                    for index, photo in enumerate(photos)
                ]
                await asyncio.wait_for(
                    bot.send_media_group(chat_id=chat_id, media=media),
                    timeout=40,
                )
        except Exception as exc:
            logger.warning("Preuves non envoyées à l'admin %s : %s", chat_id, exc)


def notify_admins_listing(chat_ids: list[int], text: str, photos: list[bytes]) -> None:
    """Envoi non bloquant (les photos restent consultables dans la console)."""

    if not chat_ids or not photos:
        return

    try:
        task = asyncio.get_running_loop().create_task(
            _send_listing_proofs(chat_ids, text, photos)
        )
    except RuntimeError:
        return

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def admin_chat_ids(db) -> list[int]:
    """ADMIN_TELEGRAM_ID + tous les comptes administrateurs en base."""

    from app.config import settings

    ids: set[int] = set()

    if settings.ADMIN_TELEGRAM_ID:
        ids.add(int(settings.ADMIN_TELEGRAM_ID))

    try:
        rows = await db.execute(
            select(User.telegram_id).where(User.is_admin.is_(True))
        )
        ids.update(int(value) for (value,) in rows.all())
    except Exception as exc:
        logger.warning("Liste des admins illisible : %s", exc)

    return sorted(ids)
