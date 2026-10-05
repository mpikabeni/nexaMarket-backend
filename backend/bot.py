from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from sqlalchemy import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Channel, Transaction, User
from app.services.telegram_service import TelegramService


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("nexmarket.bot")


# ============================================================
# SERVICES / CONFIG
# ============================================================

telegram_service = TelegramService()

FRONTEND_URL = (
    settings.FRONTEND_URL or "https://nexamarke.netlify.app"
).rstrip("/")


# ============================================================
# HELPERS
# ============================================================

def money(value, currency="XAF") -> str:
    try:
        value = Decimal(str(value or 0))
        text = f"{value:,.0f}".replace(",", " ")
    except Exception:
        text = "0"

    return f"{text} {currency}"


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 Ouvrir NexMarket",
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


async def get_user(telegram_id: int) -> Optional[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )

        return result.scalar_one_or_none()


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.effective_user or not update.message:
        return

    telegram_user = update.effective_user

    try:
        async with AsyncSessionLocal() as db:

            result = await db.execute(
                select(User).where(
                    User.telegram_id == telegram_user.id
                )
            )

            user = result.scalar_one_or_none()

            # ------------------------------------------------
            # NOUVEL UTILISATEUR
            # ------------------------------------------------

            if user is None:

                # Génération d'un identifiant Nexa unique
                nexa_id = (
                    f"NEXA-{uuid.uuid4().hex[:10].upper()}"
                )

                user = User(
                    telegram_id=telegram_user.id,
                    username=telegram_user.username,
                    first_name=telegram_user.first_name,
                    last_name=telegram_user.last_name,
                    nexa_id=nexa_id,
                    is_active=True,
                    is_admin=False,
                    language="fr",
                    preferred_currency="XAF",
                )

                db.add(user)

                await db.commit()
                await db.refresh(user)

                logger.info(
                    "Nouveau compte NexMarket créé | "
                    "telegram_id=%s | nexa_id=%s",
                    telegram_user.id,
                    user.nexa_id,
                )

                welcome_title = (
                    "🎉 <b>Bienvenue sur NexMarket !</b>"
                )

            # ------------------------------------------------
            # UTILISATEUR EXISTANT
            # ------------------------------------------------

            else:

                user.username = telegram_user.username
                user.first_name = telegram_user.first_name
                user.last_name = telegram_user.last_name

                await db.commit()

                logger.info(
                    "Compte NexMarket retrouvé | "
                    "telegram_id=%s | nexa_id=%s",
                    telegram_user.id,
                    user.nexa_id,
                )

                welcome_title = (
                    "👋 <b>Bienvenue sur NexMarket !</b>"
                )

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

        text = (
            f"{welcome_title}\n\n"
            f"Bonjour <b>{telegram_user.first_name}</b> 👋\n\n"
            "NexMarket est la marketplace dédiée à "
            "l'achat et à la vente de canaux Telegram.\n\n"
            "🛒 <b>Acheter</b> un canal\n"
            "📢 <b>Vendre</b> votre canal\n"
            "💼 <b>Suivre</b> vos transactions\n"
            "🔐 <b>Transactions sécurisées</b>\n\n"
            "<b>Votre compte NexMarket est prêt.</b>\n\n"
            "Propulsé par <b>NEXA</b>."
        )

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )

    except Exception as exc:

        logger.exception(
            "Erreur pendant /start | telegram_id=%s | erreur=%s",
            telegram_user.id,
            exc,
        )

        await update.message.reply_text(
            "❌ <b>Impossible de démarrer NexMarket</b>\n\n"
            "Une erreur est survenue lors de la connexion "
            "à votre compte.\n\n"
            "Veuillez réessayer.",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# /HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

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

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# /ABOUT
# ============================================================

async def about_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message:
        return

    text = (
        "ℹ️ <b>NexMarket</b>\n\n"
        "Marketplace dédiée à l'achat et à la vente "
        "de canaux Telegram.\n\n"
        "🏢 Créé par <b>NEXA</b>\n"
        "🌍 Afrique\n"
        "📱 Telegram Mini App\n\n"
        "Les transactions sont accompagnées par NexMarket."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# /VERIFY
# ============================================================

async def verify_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message or not update.effective_user:
        return

    # --------------------------------------------------------
    # Aucun canal fourni
    # --------------------------------------------------------

    if not context.args:

        await update.message.reply_text(
            "🔐 <b>Vérification d'un canal</b>\n\n"
            "Utilisation : "
            "<code>/verify @nomducanal</code>\n\n"
            "Le bot NexMarket doit être administrateur "
            "du canal.",
            parse_mode=ParseMode.HTML,
        )

        return

    # --------------------------------------------------------
    # Récupération du username
    # --------------------------------------------------------

    username = context.args[0].strip()

    if not username.startswith("@"):
        username = "@" + username

    await update.message.reply_text(
        "🔎 Vérification du canal en cours..."
    )

    try:

        # ----------------------------------------------------
        # Informations du canal
        # ----------------------------------------------------

        chat = await telegram_service.get_chat(
            username
        )

        # ----------------------------------------------------
        # Vérification du propriétaire
        # ----------------------------------------------------

        member = await telegram_service.get_chat_member(
            username,
            update.effective_user.id,
        )

        # ----------------------------------------------------
        # Identification du bot NexMarket
        # ----------------------------------------------------

        bot_info = await telegram_service.get_me()

        bot_id = bot_info.get("id")

        if not bot_id:
            raise RuntimeError(
                "Impossible de récupérer l'identifiant du bot."
            )

        # ----------------------------------------------------
        # Vérification du statut du bot
        # ----------------------------------------------------

        bot_member = await telegram_service.get_chat_member(
            username,
            bot_id,
        )

    except Exception as exc:

        logger.exception(
            "Erreur vérification canal %s : %s",
            username,
            exc,
        )

        await update.message.reply_text(
            "❌ Impossible de vérifier ce canal.\n\n"
            "Vérifiez que :\n"
            "• le canal existe ;\n"
            "• vous êtes propriétaire du canal ;\n"
            "• le bot NexMarket peut accéder au canal ;\n"
            "• le bot est administrateur du canal."
        )

        return

    # ========================================================
    # VÉRIFICATION PROPRIÉTAIRE
    # ========================================================

    owner_ok = (
        member.get("status") == "creator"
    )

    # ========================================================
    # VÉRIFICATION BOT ADMINISTRATEUR
    # ========================================================

    bot_status = bot_member.get("status")

    bot_admin = bot_status in {
        "administrator",
        "creator",
    }

    # ========================================================
    # INFORMATIONS CANAL
    # ========================================================

    title = chat.get("title") or username

    subscribers = chat.get(
        "member_count",
        "—",
    )

    # ========================================================
    # DÉCISION
    # ========================================================

    if not owner_ok:

        message = (
            "⚠️ Vous devez être le "
            "<b>propriétaire</b> du canal "
            "pour le proposer sur NexMarket."
        )

    elif not bot_admin:

        message = (
            "⚠️ Le bot NexMarket doit être "
            "<b>administrateur</b> du canal "
            "avant la soumission."
        )

    else:

        message = (
            "✅ <b>Canal vérifié !</b>\n\n"
            "Vous êtes bien le propriétaire du canal "
            "et le bot NexMarket est administrateur.\n\n"
            "Vous pouvez maintenant continuer "
            "dans NexMarket."
        )

    # ========================================================
    # RÉSULTAT
    # ========================================================

    await update.message.reply_text(
        f"📢 <b>{title}</b>\n\n"
        f"👥 Abonnés : <b>{subscribers}</b>\n"
        f"👤 Propriétaire : "
        f"<b>{'Oui' if owner_ok else 'Non'}</b>\n"
        f"🤖 Bot administrateur : "
        f"<b>{'Oui' if bot_admin else 'Non'}</b>\n\n"
        f"{message}",
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


# ============================================================
# /TRANSACTION
# ============================================================

async def transaction_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message or not update.effective_user:
        return

    if not context.args:

        await update.message.reply_text(
            "💼 <b>Transaction</b>\n\n"
            "Utilisation : "
            "<code>/transaction NEX-XXXXXXXX</code>",
            parse_mode=ParseMode.HTML,
        )

        return

    reference = context.args[0].strip()

    async with AsyncSessionLocal() as db:

        # ----------------------------------------------------
        # Recherche transaction
        # ----------------------------------------------------

        result = await db.execute(
            select(Transaction).where(
                Transaction.reference == reference
            )
        )

        transaction = result.scalar_one_or_none()

        if not transaction:

            await update.message.reply_text(
                "❌ Transaction introuvable."
            )

            return

        # ----------------------------------------------------
        # Recherche utilisateur
        # ----------------------------------------------------

        result = await db.execute(
            select(User).where(
                User.telegram_id
                == update.effective_user.id
            )
        )

        user = result.scalar_one_or_none()

        if not user:

            await update.message.reply_text(
                "❌ Votre compte NexMarket "
                "n'est pas encore enregistré."
            )

            return

        # ----------------------------------------------------
        # Vérification accès
        # ----------------------------------------------------

        if (
            user.id
            not in {
                transaction.buyer_id,
                transaction.seller_id,
                transaction.assigned_admin_id,
            }
            and not user.is_admin
        ):

            await update.message.reply_text(
                "⛔ Vous n'avez pas accès "
                "à cette transaction."
            )

            return

        # ----------------------------------------------------
        # Traduction statut
        # ----------------------------------------------------

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

        status = labels.get(
            transaction.status,
            transaction.status,
        )

        text = (
            "💼 <b>Transaction NexMarket</b>\n\n"
            f"Référence : "
            f"<code>{transaction.reference}</code>\n"
            f"Prix : <b>"
            f"{money(transaction.channel_price, transaction.currency)}"
            f"</b>\n"
            f"Commission : <b>"
            f"{money(transaction.platform_fee, transaction.currency)}"
            f"</b>\n"
            f"Statut : <b>{status}</b>"
        )

        await update.message.reply_text(
            text,
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


# ============================================================
# CALLBACKS
# ============================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    query = update.callback_query

    if not query:
        return

    await query.answer()

    if query.data == "help":

        await query.message.reply_text(
            "📖 Utilisez /help pour voir "
            "les commandes disponibles."
        )

    elif query.data == "about":

        await query.message.reply_text(
            "ℹ️ NexMarket — marketplace Telegram "
            "créée par NEXA."
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    logger.error(
        "Erreur Telegram",
        exc_info=context.error,
    )


# ============================================================
# BUILD APPLICATION
# ============================================================

def build_application() -> Application:

    token = (
        settings.TELEGRAM_BOT_TOKEN or ""
    ).strip()

    if not token:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN n'est pas configuré."
        )

    application = (
        Application.builder()
        .token(token)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CALLBACKS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # --------------------------------------------------------
    # ERREURS
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    application = build_application()

    logger.info(
        "NexMarket Telegram bot démarré"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
