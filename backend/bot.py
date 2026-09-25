# backend/bot.py

import asyncio
import logging
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.db import SessionLocal
from app.models import Channel, Listing, Transaction, User
from app.services.telegram_service import TelegramService


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format=(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger("nexmarket.bot")


# =========================================================
# TELEGRAM SERVICE
# =========================================================

telegram_service = TelegramService(
    settings.TELEGRAM_BOT_TOKEN
)


# =========================================================
# CONSTANTES
# =========================================================

BOT_USERNAME = (
    settings.TELEGRAM_BOT_USERNAME
    or ""
).lstrip("@")

FRONTEND_URL = (
    settings.FRONTEND_URL
    or "https://nexamarke.netlify.app"
).rstrip("/")


# =========================================================
# OUTILS
# =========================================================

def get_user_by_telegram_id(
    telegram_id: int,
):
    db = SessionLocal()

    try:
        return (
            db.query(User)
            .filter(
                User.telegram_id == telegram_id
            )
            .first()
        )
    finally:
        db.close()


def get_admin_users():
    db = SessionLocal()

    try:
        return (
            db.query(User)
            .filter(
                User.is_admin.is_(True),
                User.is_active.is_(True),
            )
            .all()
        )
    finally:
        db.close()


def format_money(
    amount,
    currency="XAF",
):
    try:
        value = float(amount)
    except (TypeError, ValueError):
        value = 0

    return (
        f"{value:,.0f}"
        .replace(",", " ")
        + f" {currency}"
    )


def main_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 Ouvrir NexMarket",
                    web_app=None,
                    url=FRONTEND_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "📖 Aide",
                    callback_data="help",
                ),
                InlineKeyboardButton(
                    "ℹ️ À propos",
                    callback_data="about",
                ),
            ],
        ]
    )


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    try:
        if not update.message:
            logger.warning("Commande /start reçue sans message.")
            return

        user = update.effective_user

        if not user:
            logger.warning("Commande /start reçue sans utilisateur.")
            return

        logger.info(
            "Commande /start reçue de Telegram ID=%s username=%s",
            user.id,
            user.username,
        )

        text = (
            "👋 <b>Bienvenue sur NexMarket</b>\n\n"
            "La marketplace dédiée à l'achat et à la "
            "vente de canaux Telegram.\n\n"
            "Avec NexMarket, vous pouvez :\n\n"
            "• rechercher des canaux Telegram\n"
            "• publier votre canal\n"
            "• acheter un canal\n"
            "• vendre votre canal\n"
            "• suivre vos transactions\n"
            "• communiquer avec l'équipe NexMarket\n\n"
            "<b>Propulsé par NEXA.</b>"
        )

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )

        logger.info(
            "/start répondu avec succès à Telegram ID=%s",
            user.id,
        )

    except Exception:
        logger.exception("Erreur pendant l'exécution de /start")

        try:
            if update.message:
                await update.message.reply_text(
                    "❌ Une erreur est survenue. "
                    "Réessaie dans quelques secondes."
                )
        except Exception:
            logger.exception(
                "Impossible d'envoyer le message d'erreur de /start"
            )


# =========================================================
# /HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "📖 <b>Aide NexMarket</b>\n\n"
        "<b>/start</b> — ouvrir NexMarket\n"
        "<b>/help</b> — afficher cette aide\n"
        "<b>/about</b> — informations sur NexMarket\n"
        "<b>/verify</b> — vérifier un canal\n"
        "<b>/transaction</b> — consulter une transaction\n\n"
        "Pour acheter ou vendre un canal, utilisez "
        "directement la Mini App NexMarket."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# =========================================================
# /ABOUT
# =========================================================

async def about_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "ℹ️ <b>NexMarket</b>\n\n"
        "NexMarket est une marketplace spécialisée "
        "dans l'achat et la vente de canaux Telegram.\n\n"
        "🏢 Créé par <b>NEXA</b>\n"
        "🌍 Afrique\n"
        "📱 Plateforme Telegram\n\n"
        "Notre objectif est de faciliter les transactions "
        "entre vendeurs et acheteurs tout en assurant "
        "un accompagnement pendant la transaction."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# =========================================================
# /VERIFY
# =========================================================

async def verify_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    if not context.args:

        text = (
            "🔐 <b>Vérification d'un canal</b>\n\n"
            "Utilisation :\n"
            "<code>/verify @nomducanal</code>\n\n"
            "Avant la vérification, ajoutez le bot "
            "NexMarket comme administrateur du canal."
        )

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
        )

        return

    channel_username = context.args[0].strip()

    if not channel_username.startswith("@"):
        channel_username = (
            "@" + channel_username
        )

    await update.message.reply_text(
        "🔎 Vérification du canal en cours..."
    )

    try:

        result = await telegram_service.verify_channel(
            channel_username
        )

    except Exception as exc:

        logger.exception(
            "Erreur vérification canal"
        )

        await update.message.reply_text(
            "❌ Impossible de vérifier ce canal "
            "pour le moment.\n\n"
            "Vérifiez que le canal existe et que le "
            "bot possède les droits nécessaires."
        )

        return

    if not result:

        await update.message.reply_text(
            "❌ Canal introuvable ou impossible à vérifier."
        )

        return

    title = result.get("title") or channel_username
    subscribers = result.get(
        "subscribers_count",
        0,
    )

    bot_is_admin = result.get(
        "bot_is_admin",
        False,
    )

    await update.message.reply_text(
        (
            "✅ <b>Canal trouvé</b>\n\n"
            f"📢 <b>{title}</b>\n"
            f"👥 Abonnés : <b>{subscribers}</b>\n"
            f"🔗 {channel_username}\n\n"
            f"🤖 Bot administrateur : "
            f"<b>{'Oui' if bot_is_admin else 'Non'}</b>\n\n"
            "Vous pouvez maintenant continuer "
            "la procédure depuis NexMarket."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛒 Ouvrir NexMarket",
                        url=FRONTEND_URL,
                    )
                ]
            ]
        ),
    )


# =========================================================
# /TRANSACTION
# =========================================================

async def transaction_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    if not context.args:

        await update.message.reply_text(
            (
                "💼 <b>Transaction</b>\n\n"
                "Utilisation :\n"
                "<code>/transaction NEX-XXXXXXXX</code>"
            ),
            parse_mode=ParseMode.HTML,
        )

        return

    reference = context.args[0].strip()

    db = SessionLocal()

    try:

        transaction = (
            db.query(Transaction)
            .filter(
                Transaction.reference == reference
            )
            .first()
        )

        if not transaction:

            await update.message.reply_text(
                "❌ Transaction introuvable."
            )

            return

        current_user = (
            db.query(User)
            .filter(
                User.telegram_id == user.id
            )
            .first()
        )

        if not current_user:

            await update.message.reply_text(
                "❌ Votre compte NexMarket "
                "n'est pas encore enregistré."
            )

            return

        allowed = (
            transaction.buyer_id
            == current_user.id
            or
            transaction.seller_id
            == current_user.id
            or
            (
                current_user.is_admin
            )
        )

        if not allowed:

            await update.message.reply_text(
                "⛔ Vous n'avez pas accès à cette transaction."
            )

            return

        status_labels = {
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

        status = status_labels.get(
            transaction.status,
            transaction.status,
        )

        text = (
            "💼 <b>Transaction NexMarket</b>\n\n"
            f"Référence : "
            f"<code>{transaction.reference}</code>\n\n"
            f"Prix : "
            f"<b>{format_money(transaction.channel_price, transaction.currency)}</b>\n"
            f"Commission : "
            f"<b>{format_money(transaction.platform_fee, transaction.currency)}</b>\n"
            f"Statut : <b>{status}</b>"
        )

        buttons = [
            [
                InlineKeyboardButton(
                    "💬 Ouvrir NexMarket",
                    url=FRONTEND_URL,
                )
            ]
        ]

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

    finally:
        db.close()


# =========================================================
# NOTIFICATION ADMIN
# =========================================================

async def notify_admins_new_transaction(
    application: Application,
    transaction_id: int,
):

    db = SessionLocal()

    try:

        transaction = (
            db.query(Transaction)
            .filter(
                Transaction.id == transaction_id
            )
            .first()
        )

        if not transaction:
            return

        buyer = (
            db.query(User)
            .filter(
                User.id == transaction.buyer_id
            )
            .first()
        )

        seller = (
            db.query(User)
            .filter(
                User.id == transaction.seller_id
            )
            .first()
        )

        listing = (
            db.query(Listing)
            .filter(
                Listing.id == transaction.listing_id
            )
            .first()
        )

        if not buyer or not seller:
            return

        buyer_name = (
            f"@{buyer.username}"
            if buyer.username
            else buyer.first_name or "Acheteur"
        )

        seller_name = (
            f"@{seller.username}"
            if seller.username
            else seller.first_name or "Vendeur"
        )

        channel_title = "Canal Telegram"

        if listing:

            channel = (
                db.query(Channel)
                .filter(
                    Channel.id == listing.channel_id
                )
                .first()
            )

            if channel:
                channel_title = (
                    channel.title
                    or channel.username
                    or channel_title
                )

        text = (
            "🔔 <b>NOUVELLE TRANSACTION</b>\n\n"
            f"📢 Canal : <b>{channel_title}</b>\n"
            f"👤 Acheteur : {buyer_name}\n"
            f"👤 Vendeur : {seller_name}\n\n"
            f"💰 Prix : "
            f"<b>{format_money(transaction.channel_price, transaction.currency)}</b>\n"
            f"🧾 Référence : "
            f"<code>{transaction.reference}</code>\n\n"
            "Une intervention administrative est nécessaire."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛠 Prendre en charge",
                        callback_data=(
                            f"take_transaction:"
                            f"{transaction.id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📋 Ouvrir NexMarket",
                        url=FRONTEND_URL,
                    )
                ],
            ]
        )

        admins = get_admin_users()

        for admin in admins:

            try:

                await application.bot.send_message(
                    chat_id=admin.telegram_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )

            except Exception:

                logger.exception(
                    "Impossible de notifier l'admin %s",
                    admin.id,
                )

    finally:
        db.close()


# =========================================================
# CALLBACK ADMIN
# =========================================================

async def take_transaction_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    admin = query.from_user

    current_admin = get_user_by_telegram_id(
        admin.id
    )

    if not current_admin or not current_admin.is_admin:

        await query.answer(
            "Accès réservé aux administrateurs.",
            show_alert=True,
        )

        return

    data = query.data or ""

    if not data.startswith(
        "take_transaction:"
    ):

        return

    try:

        transaction_id = int(
            data.split(":")[1]
        )

    except (IndexError, ValueError):

        await query.answer(
            "Transaction invalide.",
            show_alert=True,
        )

        return

    db = SessionLocal()

    try:

        transaction = (
            db.query(Transaction)
            .filter(
                Transaction.id
                == transaction_id
            )
            .first()
        )

        if not transaction:

            await query.answer(
                "Transaction introuvable.",
                show_alert=True,
            )

            return

        if transaction.assigned_admin_id:

            await query.answer(
                "Cette transaction est déjà prise en charge.",
                show_alert=True,
            )

            return

        if transaction.status not in {
            "waiting_admin",
            "assigned",
        }:

            await query.answer(
                "Cette transaction n'est plus disponible.",
                show_alert=True,
            )

            return

        transaction.assigned_admin_id = (
            current_admin.id
        )

        transaction.status = "assigned"

        transaction.admin_note = (
            "Transaction prise en charge "
            "via le bot Telegram."
        )

        db.commit()

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            (
                "✅ <b>Transaction prise en charge</b>\n\n"
                f"Référence : "
                f"<code>{transaction.reference}</code>\n"
                f"Administrateur : "
                f"<b>{current_admin.first_name or 'Admin'}</b>\n\n"
                "Vous pouvez maintenant poursuivre "
                "le traitement depuis l'espace "
                "administrateur NexMarket."
            ),
            parse_mode=ParseMode.HTML,
        )

        # Notification acheteur/vendeur
        buyer = (
            db.query(User)
            .filter(
                User.id == transaction.buyer_id
            )
            .first()
        )

        seller = (
            db.query(User)
            .filter(
                User.id == transaction.seller_id
            )
            .first()
        )

        notify_text = (
            "🛠 <b>Votre transaction est prise en charge</b>\n\n"
            f"Référence : "
            f"<code>{transaction.reference}</code>\n\n"
            "Un administrateur NexMarket vient "
            "de prendre en charge votre transaction."
        )

        recipients = []

        if buyer:
            recipients.append(buyer)

        if seller and (
            not buyer
            or seller.id != buyer.id
        ):
            recipients.append(seller)

        for recipient in recipients:

            try:

                await context.bot.send_message(
                    chat_id=recipient.telegram_id,
                    text=notify_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "💬 Ouvrir NexMarket",
                                    url=FRONTEND_URL,
                                )
                            ]
                        ]
                    ),
                )

            except Exception:

                logger.exception(
                    "Notification transaction impossible."
                )

    finally:
        db.close()


# =========================================================
# MESSAGE PRIVÉ
# =========================================================

async def private_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if update.effective_chat.type != "private":
        return

    text = (
        "👋 Je suis le bot officiel de <b>NexMarket</b>.\n\n"
        "Pour acheter, vendre ou gérer un canal Telegram, "
        "ouvre simplement NexMarket."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# =========================================================
# MESSAGE DE GROUPE
# =========================================================

async def group_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    message = update.message

    if message.chat.type not in {
        "group",
        "supergroup",
    }:
        return

    text = message.text or ""

    mention_bot = False

    if BOT_USERNAME:

        mention_bot = (
            f"@{BOT_USERNAME.lower()}"
            in text.lower()
        )

    if not mention_bot:
        return

    await message.reply_text(
        (
            "👋 <b>NexMarket</b> ici !\n\n"
            "Si tu veux acheter ou vendre un canal "
            "Telegram, utilise la Mini App NexMarket."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Erreur Telegram",
        exc_info=context.error,
    )


# =========================================================
# CONSTRUCTION DE L'APPLICATION
# =========================================================

def build_application():

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN n'est pas configuré."
        )

    logger.info("Initialisation du bot Telegram...")

    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN.strip())
        .build()
    )

    # -----------------------------
    # COMMANDES
    # -----------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "about",
            about_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "verify",
            verify_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "transaction",
            transaction_command,
        )
    )

    # -----------------------------
    # CALLBACKS
    # -----------------------------

    application.add_handler(
        CallbackQueryHandler(
            take_transaction_callback,
            pattern=r"^take_transaction:",
        )
    )

    # -----------------------------
    # BOUTONS GÉNÉRAUX
    # -----------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_query_handler,
            pattern=r"^(help|about)$",
        )
    )

    # -----------------------------
    # MESSAGES PRIVÉS
    # -----------------------------

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & ~filters.COMMAND,
            private_message_handler,
        )
    )

    # -----------------------------
    # GROUPES
    # -----------------------------

    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & ~filters.COMMAND,
            group_message_handler,
        )
    )

    # -----------------------------
    # ERREURS
    # -----------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Handlers Telegram enregistrés avec succès."
    )

    return application


# =========================================================
# CALLBACKS GÉNÉRAUX
# =========================================================

async def callback_query_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    if query.data == "help":

        await query.message.reply_text(
            (
                "📖 <b>Aide NexMarket</b>\n\n"
                "<b>/start</b> — ouvrir NexMarket\n"
                "<b>/verify @canal</b> — vérifier un canal\n"
                "<b>/transaction REF</b> — consulter une transaction\n\n"
                "Pour les opérations complètes, utilise "
                "la Mini App NexMarket."
            ),
            parse_mode=ParseMode.HTML,
        )

    elif query.data == "about":

        await query.message.reply_text(
            (
                "ℹ️ <b>NexMarket</b>\n\n"
                "Marketplace spécialisée dans l'achat "
                "et la vente de canaux Telegram.\n\n"
                "🏢 Créé par <b>NEXA</b>."
            ),
            parse_mode=ParseMode.HTML,
        )


# =========================================================
# MAIN
# =========================================================

def main():

    try:
        logger.info(
            "========================================"
        )
        logger.info(
            "NexMarket Bot démarrage..."
        )
        logger.info(
            "========================================"
        )

        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN n'est pas configuré."
            )

        logger.info(
            "Token Telegram détecté."
        )

        application = build_application()

        logger.info(
            "Application Telegram construite."
        )

        logger.info(
            "Démarrage du polling Telegram..."
        )

        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )

    except Exception:
        logger.exception(
            "ERREUR FATALE DU BOT NEXMARKET"
        )
        raise


if __name__ == "__main__":
    main()