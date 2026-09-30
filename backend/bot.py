from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Channel, Transaction, User
from app.services.telegram_service import TelegramService
from sqlalchemy import select

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nexmarket.bot")

telegram_service = TelegramService()
FRONTEND_URL = (settings.FRONTEND_URL or "https://nexamarke.netlify.app").rstrip("/")


def money(value, currency="XAF") -> str:
    try:
        value = Decimal(str(value or 0))
        text = f"{value:,.0f}".replace(",", " ")
    except Exception:
        text = "0"
    return f"{text} {currency}"


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Ouvrir NexMarket", url=FRONTEND_URL)],
        [
            InlineKeyboardButton("📖 Aide", callback_data="help"),
            InlineKeyboardButton("ℹ️ À propos", callback_data="about"),
        ],
    ])


async def get_user(telegram_id: int) -> Optional[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    text = (
        "👋 <b>Bienvenue sur NexMarket</b>\n\n"
        "La marketplace dédiée à l'achat et à la vente de canaux Telegram.\n\n"
        "• Rechercher des canaux\n"
        "• Publier votre canal\n"
        "• Acheter ou vendre\n"
        "• Suivre vos transactions\n"
        "• Échanger avec l'équipe NexMarket\n\n"
        "<b>Propulsé par NEXA.</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "📖 <b>Aide NexMarket</b>\n\n"
        "<b>/start</b> — ouvrir NexMarket\n"
        "<b>/help</b> — afficher cette aide\n"
        "<b>/about</b> — informations sur NexMarket\n"
        "<b>/verify @canal</b> — vérifier un canal\n"
        "<b>/transaction NEX-...</b> — consulter une transaction\n\n"
        "Les achats et ventes se poursuivent depuis la Mini App."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "ℹ️ <b>NexMarket</b>\n\n"
        "Marketplace dédiée à l'achat et à la vente de canaux Telegram.\n\n"
        "🏢 Créé par <b>NEXA</b>\n"
        "🌍 Afrique\n"
        "📱 Telegram Mini App\n\n"
        "Les transactions sont accompagnées par NexMarket."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not context.args:
        await update.message.reply_text(
            "🔐 <b>Vérification d'un canal</b>\n\n"
            "Utilisation : <code>/verify @nomducanal</code>\n\n"
            "Le bot NexMarket doit être administrateur du canal.",
            parse_mode=ParseMode.HTML,
        )
        return

    username = context.args[0].strip()
    if not username.startswith("@"):
        username = "@" + username

    await update.message.reply_text("🔎 Vérification du canal en cours...")
    try:
        chat = await telegram_service.get_chat(username)
        member = await telegram_service.get_chat_member(username, update.effective_user.id)
        bot_member = await telegram_service.get_chat_member(username, (await telegram_service.get_me()).get("id"))
    except Exception as exc:
        logger.exception("Erreur vérification canal: %s", exc)
        await update.message.reply_text(
            "❌ Impossible de vérifier ce canal. Vérifiez que le canal existe et que le bot est administrateur."
        )
        return

    owner_ok = member.get("status") == "creator"
    bot_status = bot_member.get("status")
    bot_admin = bot_status in {"administrator", "creator"}
    title = chat.get("title") or username
    subscribers = chat.get("member_count", "—")

    if not owner_ok:
        message = "⚠️ Vous devez être le propriétaire du canal pour le proposer sur NexMarket."
    elif not bot_admin:
        message = "⚠️ Le bot NexMarket doit être administrateur du canal avant la soumission."
    else:
        message = "✅ Le canal satisfait les vérifications Telegram de base. Vous pouvez continuer dans NexMarket."

    await update.message.reply_text(
        f"📢 <b>{title}</b>\n"
        f"👥 Abonnés : <b>{subscribers}</b>\n"
        f"👤 Propriétaire : <b>{'Oui' if owner_ok else 'Non'}</b>\n"
        f"🤖 Bot administrateur : <b>{'Oui' if bot_admin else 'Non'}</b>\n\n"
        f"{message}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Ouvrir NexMarket", url=FRONTEND_URL)]]),
    )


async def transaction_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not context.args:
        await update.message.reply_text(
            "💼 <b>Transaction</b>\n\nUtilisation : <code>/transaction NEX-XXXXXXXX</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    reference = context.args[0].strip()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Transaction).where(Transaction.reference == reference))
        transaction = result.scalar_one_or_none()
        if not transaction:
            await update.message.reply_text("❌ Transaction introuvable.")
            return

        result = await db.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ Votre compte NexMarket n'est pas encore enregistré.")
            return

        if user.id not in {transaction.buyer_id, transaction.seller_id, transaction.assigned_admin_id} and not user.is_admin:
            await update.message.reply_text("⛔ Vous n'avez pas accès à cette transaction.")
            return

        labels = {
            "pending_payment": "Paiement en attente",
            "payment_confirmed": "Paiement confirmé",
            "waiting_admin": "En attente d'un administrateur",
            "assigned": "Administrateur assigné",
            "transfer_pending": "Transfert en cours",
            "completed": "Terminée",
            "cancelled": "Annulée",
            "disputed": "Litige",
            "refunded": "Remboursée",
        }
        status = labels.get(transaction.status, transaction.status)
        text = (
            "💼 <b>Transaction NexMarket</b>\n\n"
            f"Référence : <code>{transaction.reference}</code>\n"
            f"Prix : <b>{money(transaction.channel_price, transaction.currency)}</b>\n"
            f"Commission : <b>{money(transaction.platform_fee, transaction.currency)}</b>\n"
            f"Statut : <b>{status}</b>"
        )
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Ouvrir NexMarket", url=FRONTEND_URL)]])
        )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if query.data == "help":
        await query.message.reply_text("📖 Utilisez /help pour voir les commandes disponibles.")
    elif query.data == "about":
        await query.message.reply_text("ℹ️ NexMarket — marketplace Telegram créée par NEXA.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Erreur Telegram", exc_info=context.error)


def build_application() -> Application:
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN n'est pas configuré.")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("verify", verify_command))
    application.add_handler(CommandHandler("transaction", transaction_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    application = build_application()
    logger.info("NexMarket Telegram bot démarré")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
