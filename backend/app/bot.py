from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
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

from sqlalchemy import func, select

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
    """
    Bouton principal : ouvre réellement la Telegram Mini App.
    """

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 Ouvrir NexMarket",
                    web_app=WebAppInfo(url=FRONTEND_URL),
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


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📊 Statistiques",
                    callback_data="admin_stats",
                ),
                InlineKeyboardButton(
                    "👥 Utilisateurs",
                    callback_data="admin_users",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📢 Diffusion",
                    callback_data="admin_broadcast",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🛒 Ouvrir NexMarket",
                    web_app=WebAppInfo(url=FRONTEND_URL),
                )
            ],
        ]
    )


async def get_user(telegram_id: int) -> Optional[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )

        return result.scalar_one_or_none()


async def is_admin_user(telegram_id: int) -> bool:
    user = await get_user(telegram_id)

    if not user:
        return False

    return bool(user.is_admin)


async def admin_required(
    update: Update,
) -> bool:
    if not update.effective_user or not update.message:
        return False

    if not await is_admin_user(update.effective_user.id):
        await update.message.reply_text(
            "⛔ <b>Accès refusé.</b>\n\n"
            "Cette commande est réservée aux administrateurs "
            "de NexMarket.",
            parse_mode=ParseMode.HTML,
        )
        return False

    return True


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

            # Sauvegarde de l'ID avant de fermer la session
            nexa_id = user.nexa_id

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
            "🆔 <b>Votre NEXA ID</b>\n"
            f"<code>{nexa_id}</code>\n\n"
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
                        web_app=WebAppInfo(
                            url=FRONTEND_URL
                        ),
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
                            web_app=WebAppInfo(
                                url=FRONTEND_URL
                            ),
                        )
                    ]
                ]
            ),
        )


# ============================================================
# ADMIN HELP
# ============================================================

async def adminhelp_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    text = (
        "👑 <b>Commandes administrateur NexMarket</b>\n\n"
        "<b>/admin</b> — panneau administrateur\n"
        "<b>/stats</b> — statistiques générales\n"
        "<b>/users</b> — statistiques utilisateurs\n"
        "<b>/broadcast</b> — envoyer un message à tous\n"
        "<b>/ban TELEGRAM_ID</b> — désactiver un compte\n"
        "<b>/unban TELEGRAM_ID</b> — réactiver un compte\n"
        "<b>/adminhelp</b> — cette aide\n\n"
        "🔐 Ces commandes sont réservées aux administrateurs."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


# ============================================================
# /ADMIN
# ============================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    await update.message.reply_text(
        "👑 <b>Panneau administrateur NexMarket</b>\n\n"
        "Choisissez une action :",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


# ============================================================
# /STATS
# ============================================================

async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    async with AsyncSessionLocal() as db:

        users_count = await db.scalar(
            select(func.count()).select_from(User)
        )

        active_users = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True))
        )

        channels_count = await db.scalar(
            select(func.count()).select_from(Channel)
        )

        transactions_count = await db.scalar(
            select(func.count()).select_from(Transaction)
        )

    text = (
        "📊 <b>Statistiques NexMarket</b>\n\n"
        f"👥 Utilisateurs : <b>{users_count or 0}</b>\n"
        f"🟢 Utilisateurs actifs : <b>{active_users or 0}</b>\n"
        f"📢 Canaux : <b>{channels_count or 0}</b>\n"
        f"💼 Transactions : <b>{transactions_count or 0}</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


# ============================================================
# /USERS
# ============================================================

async def users_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    async with AsyncSessionLocal() as db:

        users_count = await db.scalar(
            select(func.count()).select_from(User)
        )

        admins_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True))
        )

        active_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True))
        )

        inactive_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(False))
        )

    text = (
        "👥 <b>Utilisateurs NexMarket</b>\n\n"
        f"Total : <b>{users_count or 0}</b>\n"
        f"🟢 Actifs : <b>{active_count or 0}</b>\n"
        f"🔴 Désactivés : <b>{inactive_count or 0}</b>\n"
        f"👑 Administrateurs : <b>{admins_count or 0}</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# /BAN
# ============================================================

async def ban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "🚫 <b>Désactiver un utilisateur</b>\n\n"
            "Utilisation :\n"
            "<code>/ban TELEGRAM_ID</code>",
            parse_mode=ParseMode.HTML,
        )

        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:

        await update.message.reply_text(
            "❌ Le Telegram ID doit être un nombre."
        )

        return

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(User).where(
                User.telegram_id == telegram_id
            )
        )

        user = result.scalar_one_or_none()

        if not user:

            await update.message.reply_text(
                "❌ Utilisateur introuvable."
            )

            return

        user.is_active = False

        await db.commit()

        await update.message.reply_text(
            "🚫 <b>Utilisateur désactivé.</b>\n\n"
            f"Telegram ID : <code>{telegram_id}</code>\n"
            f"NEXA ID : <code>{user.nexa_id}</code>",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# /UNBAN
# ============================================================

async def unban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "✅ <b>Réactiver un utilisateur</b>\n\n"
            "Utilisation :\n"
            "<code>/unban TELEGRAM_ID</code>",
            parse_mode=ParseMode.HTML,
        )

        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:

        await update.message.reply_text(
            "❌ Le Telegram ID doit être un nombre."
        )

        return

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(User).where(
                User.telegram_id == telegram_id
            )
        )

        user = result.scalar_one_or_none()

        if not user:

            await update.message.reply_text(
                "❌ Utilisateur introuvable."
            )

            return

        user.is_active = True

        await db.commit()

        await update.message.reply_text(
            "✅ <b>Utilisateur réactivé.</b>\n\n"
            f"Telegram ID : <code>{telegram_id}</code>\n"
            f"NEXA ID : <code>{user.nexa_id}</code>",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# /BROADCAST
# ============================================================

async def broadcast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await admin_required(update):
        return

    context.user_data["waiting_broadcast"] = True

    await update.message.reply_text(
        "📢 <b>Diffusion NexMarket</b>\n\n"
        "Envoie maintenant le message que tu veux "
        "envoyer aux utilisateurs actifs.\n\n"
        "❌ Pour annuler : /cancel",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# /CANCEL
# ============================================================

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message:
        return

    context.user_data.pop("waiting_broadcast", None)

    await update.message.reply_text(
        "❌ Diffusion annulée."
    )


# ============================================================
# BROADCAST MESSAGE HANDLER
# ============================================================

async def broadcast_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message or not update.effective_user:
        return

    if not context.user_data.get("waiting_broadcast"):
        return

    # Vérification admin
    if not await is_admin_user(update.effective_user.id):

        context.user_data.pop("waiting_broadcast", None)

        await update.message.reply_text(
            "⛔ Accès refusé."
        )

        return

    context.user_data.pop("waiting_broadcast", None)

    message = update.message.text

    if not message:
        await update.message.reply_text(
            "❌ Le message texte est vide."
        )
        return

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(User.telegram_id).where(
                User.is_active.is_(True)
            )
        )

        telegram_ids = result.scalars().all()

    if not telegram_ids:

        await update.message.reply_text(
            "ℹ️ Aucun utilisateur actif à contacter."
        )

        return

    await update.message.reply_text(
        f"📢 Diffusion lancée vers "
        f"<b>{len(telegram_ids)}</b> utilisateurs.",
        parse_mode=ParseMode.HTML,
    )

    sent = 0
    failed = 0

    for telegram_id in telegram_ids:

        try:

            await context.bot.send_message(
                chat_id=telegram_id,
                text=message,
            )

            sent += 1

        except Exception as exc:

            failed += 1

            logger.warning(
                "Broadcast impossible vers %s : %s",
                telegram_id,
                exc,
            )

        # Petite pause pour éviter les limites Telegram
        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "✅ <b>Diffusion terminée</b>\n\n"
        f"📨 Envoyés : <b>{sent}</b>\n"
        f"❌ Échecs : <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
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

    elif query.data == "admin_stats":

        if not query.from_user:
            return

        if not await is_admin_user(query.from_user.id):

            await query.message.reply_text(
                "⛔ Accès refusé."
            )
            return

        async with AsyncSessionLocal() as db:

            users_count = await db.scalar(
                select(func.count()).select_from(User)
            )

            active_users = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.is_active.is_(True))
            )

            channels_count = await db.scalar(
                select(func.count()).select_from(Channel)
            )

            transactions_count = await db.scalar(
                select(func.count()).select_from(Transaction)
            )

        await query.message.reply_text(
            "📊 <b>Statistiques NexMarket</b>\n\n"
            f"👥 Utilisateurs : <b>{users_count or 0}</b>\n"
            f"🟢 Actifs : <b>{active_users or 0}</b>\n"
            f"📢 Canaux : <b>{channels_count or 0}</b>\n"
            f"💼 Transactions : <b>{transactions_count or 0}</b>",
            parse_mode=ParseMode.HTML,
        )

    elif query.data == "admin_users":

        if not query.from_user:
            return

        if not await is_admin_user(query.from_user.id):

            await query.message.reply_text(
                "⛔ Accès refusé."
            )
            return

        async with AsyncSessionLocal() as db:

            total = await db.scalar(
                select(func.count()).select_from(User)
            )

            active = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.is_active.is_(True))
            )

            admins = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.is_admin.is_(True))
            )

        await query.message.reply_text(
            "👥 <b>Utilisateurs</b>\n\n"
            f"Total : <b>{total or 0}</b>\n"
            f"Actifs : <b>{active or 0}</b>\n"
            f"Administrateurs : <b>{admins or 0}</b>",
            parse_mode=ParseMode.HTML,
        )

    elif query.data == "admin_broadcast":

        if not query.from_user:
            return

        if not await is_admin_user(query.from_user.id):

            await query.message.reply_text(
                "⛔ Accès refusé."
            )
            return

        context.user_data["waiting_broadcast"] = True

        await query.message.reply_text(
            "📢 <b>Diffusion</b>\n\n"
            "Envoie maintenant le message à diffuser.\n\n"
            "❌ /cancel pour annuler.",
            parse_mode=ParseMode.HTML,
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
    # COMMANDES UTILISATEURS
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
    # COMMANDES ADMIN
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "adminhelp",
            adminhelp_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            users_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command,
        )
    )

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            broadcast_message_handler,
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
