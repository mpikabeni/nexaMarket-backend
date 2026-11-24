from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from sqlalchemy import func, select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import BotChat, Channel, Listing, Transaction, User, Wallet
from app.services.chat_service import ROLE_LABELS, post_message, role_for
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
                    web_app=WebAppInfo(url=FRONTEND_URL),
                )
            ],
        ]
    )


# Aide au retrait : plus aucun compte externe à créer. On retire directement
# vers son numéro Mobile Money (MTN, Airtel, Orange, Moov, Wave...).
WITHDRAW_HELP_TEXT = (
    "💸 <b>Recevoir ton argent</b>\n\n"
    "Quand tu vends un canal, ton argent est envoyé sur ton "
    "<b>compte JessiKaPay</b> (ton numéro <b>JP</b>), une fois le paiement "
    "de l'acheteur confirmé et la livraison validée par l'équipe NexMarket.\n\n"
    "1️⃣ Mets ton canal en vente dans NexMarket et entre ton <b>numéro JP</b>.\n"
    "2️⃣ L'acheteur paie : son argent reste <b>bloqué</b> jusqu'à la livraison.\n"
    "3️⃣ Après la libération, l'argent arrive sur ton <b>compte JessiKaPay</b>.\n"
    "4️⃣ Depuis JessiKaPay, tu le retires ensuite vers ton Mobile Money.\n\n"
    "Tu es prévenu ici dès que l'argent est envoyé."
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
    """
    Un utilisateur est administrateur si :
    1. son Telegram ID correspond à ADMIN_TELEGRAM_ID dans Render
    OU
    2. son compte possède is_admin=True.
    """

    # Administrateur principal défini dans Render
    if (
        settings.ADMIN_TELEGRAM_ID
        and telegram_id == settings.ADMIN_TELEGRAM_ID
    ):
        return True

    # Administrateurs enregistrés en base
    user = await get_user(telegram_id)

    if not user:
        return False

    return bool(user.is_admin)


async def admin_required(update: Update) -> bool:
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
# CANAL OBLIGATOIRE : il faut rejoindre @Nexa_CG pour utiliser le bot
# ============================================================
# Un « portier » (groupe -1) s'exécute AVANT toutes les commandes et tous
# les boutons. Les administrateurs NexMarket en sont dispensés.
# Si Telegram ne permet pas de vérifier (bot non administrateur du canal,
# canal introuvable, réseau), l'accès n'est PAS bloqué pour tout le monde :
# l'erreur est écrite dans les logs (« Vérification du canal impossible »).

REQUIRED_CHANNEL = (settings.REQUIRED_CHANNEL or "@Nexa_CG").strip()
REQUIRED_CHANNEL_URL = (
    settings.REQUIRED_CHANNEL_URL or "https://t.me/Nexa_CG"
).strip()

CHECK_SUBSCRIPTION_CALLBACK = "check_subscription"
MEMBER_CACHE_SECONDS = 600
_member_cache: dict[int, float] = {}


def join_channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Rejoindre le canal NEXA",
                    url=REQUIRED_CHANNEL_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ J'ai rejoint le canal",
                    callback_data=CHECK_SUBSCRIPTION_CALLBACK,
                )
            ],
        ]
    )


async def is_channel_member(bot, user_id: int) -> Optional[bool]:
    """True = membre, False = pas membre, None = vérification impossible."""

    cached_until = _member_cache.get(user_id)

    if cached_until and cached_until > time.monotonic():
        return True

    try:
        member = await bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL,
            user_id=user_id,
        )

    except TelegramError as exc:
        logger.error(
            "Vérification du canal impossible (%s) : %s. "
            "Le bot doit être administrateur de %s.",
            type(exc).__name__,
            exc,
            REQUIRED_CHANNEL,
        )
        return None

    if member.status in (
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    ) or (
        member.status == ChatMemberStatus.RESTRICTED
        and getattr(member, "is_member", False)
    ):
        if len(_member_cache) > 5000:
            _member_cache.clear()

        _member_cache[user_id] = time.monotonic() + MEMBER_CACHE_SECONDS
        return True

    _member_cache.pop(user_id, None)
    return False


async def subscription_gate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    user = update.effective_user
    chat = update.effective_chat
    query = update.callback_query

    # Seuls les messages et boutons en conversation privée sont contrôlés.
    if (
        not user
        or user.is_bot
        or not chat
        or chat.type != ChatType.PRIVATE
        or (update.message is None and query is None)
    ):
        return

    if await is_admin_user(user.id):
        return

    is_check = bool(
        query and query.data == CHECK_SUBSCRIPTION_CALLBACK
    )

    member = await is_channel_member(context.bot, user.id)

    # Membre (ou vérification impossible) : accès normal.
    if member is not False:

        if is_check:
            await query.answer("✅ Merci, bienvenue !")

            try:
                await query.message.delete()
            except Exception:
                pass

            await start_command(update, context)
            raise ApplicationHandlerStop

        return

    # Pas membre : accès refusé.
    if query:
        await query.answer(
            "❌ Rejoins d'abord le canal NEXA, puis réessaie."
            if is_check
            else "Rejoins d'abord le canal NEXA pour utiliser le bot.",
            show_alert=True,
        )

        if is_check:
            raise ApplicationHandlerStop

    target = update.effective_message

    if target:
        await target.reply_text(
            "🔒 <b>Accès réservé aux membres</b>\n\n"
            "Pour utiliser <b>NexMarket</b>, tu dois d'abord rejoindre "
            "notre canal officiel <b>NEXA</b>.\n\n"
            "1️⃣ Appuie sur <b>Rejoindre le canal NEXA</b>\n"
            "2️⃣ Reviens ici et appuie sur "
            "<b>J'ai rejoint le canal</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=join_channel_keyboard(),
        )

    raise ApplicationHandlerStop


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    message = update.effective_message

    if not update.effective_user or not message:
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

                    # L'ADMIN_TELEGRAM_ID de Render devient
                    # automatiquement administrateur.
                    is_admin=(
                        bool(settings.ADMIN_TELEGRAM_ID)
                        and telegram_user.id
                        == settings.ADMIN_TELEGRAM_ID
                    ),

                    language="fr",
                    preferred_currency="XAF",
                )

                db.add(user)

                # Un wallet est indispensable (dépôts / retraits).
                # Avant, seul /api/auth le créait.
                await db.flush()

                db.add(
                    Wallet(
                        user_id=user.id,
                        available_balance=0,
                        blocked_balance=0,
                        total_revenue=0,
                        currency="XAF",
                    )
                )

                await db.commit()
                await db.refresh(user)

                logger.info(
                    "Nouveau compte NexMarket créé | "
                    "telegram_id=%s | nexa_id=%s | admin=%s",
                    telegram_user.id,
                    user.nexa_id,
                    user.is_admin,
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

                # Si l'utilisateur correspond à
                # ADMIN_TELEGRAM_ID dans Render, on le marque admin.
                if (
                    settings.ADMIN_TELEGRAM_ID
                    and telegram_user.id
                    == settings.ADMIN_TELEGRAM_ID
                ):
                    user.is_admin = True

                await db.commit()

                logger.info(
                    "Compte NexMarket retrouvé | "
                    "telegram_id=%s | nexa_id=%s | admin=%s",
                    telegram_user.id,
                    user.nexa_id,
                    user.is_admin,
                )

                welcome_title = (
                    "👋 <b>Bienvenue sur NexMarket !</b>"
                )

            # On conserve le même NEXA ID
            nexa_id = user.nexa_id

            # Le NEXA ID n'est montré qu'après la création du compte dans la
            # mini-app (ou pour un compte déjà existant avant cette règle).
            has_account = bool(user.onboarded_at)

            if not has_account:
                try:
                    from datetime import datetime as _dt

                    cutoff = _dt.fromisoformat(settings.LEGACY_ACCOUNTS_BEFORE)
                    created = user.created_at

                    if created is not None and created.tzinfo is None:
                        created = created.replace(tzinfo=cutoff.tzinfo)

                    has_account = bool(created and created < cutoff)
                except Exception:
                    has_account = False

            # Statut admin
            is_admin = bool(user.is_admin)

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
            + (
                "🆔 <b>Votre NEXA ID</b>\n"
                f"<code>{nexa_id}</code>\n\n"
                "<b>Votre compte NexMarket est prêt.</b>\n\n"
                if has_account
                else "👉 <b>Ouvrez NexMarket et créez votre compte</b> "
                "pour obtenir votre NEXA ID.\n\n"
            )
            +
            "💸 <b>Tes gains</b> arrivent sur ton compte JessiKaPay "
            "après le paiement : voir /retrait.\n\n"
            "Propulsé par <b>NEXA</b>."
        )

        if is_admin:
            text += (
                "\n\n👑 <b>Administrateur NexMarket</b>\n"
                "Utilisez /admin pour ouvrir le panneau."
            )

        try:
            await context.bot.set_chat_menu_button(
                chat_id=telegram_user.id,
                menu_button=MenuButtonWebApp(
                    text="NexMarket",
                    web_app=WebAppInfo(url=FRONTEND_URL),
                ),
            )
        except Exception as menu_error:
            logger.warning(
                "Impossible de configurer le bouton Mini App du menu | telegram_id=%s | erreur=%s",
                telegram_user.id,
                menu_error,
            )

        await message.reply_text(
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

        await message.reply_text(
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
        "<b>/transaction NEX-...</b> — consulter une transaction\n"
        "<b>/retrait</b> — comment recevoir ton argent\n\n"
        "Les achats et ventes se poursuivent depuis la Mini App."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# /RETRAIT (aide au retrait)
# ============================================================

async def withdraw_help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message:
        return

    await update.message.reply_text(
        WITHDRAW_HELP_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
        disable_web_page_preview=True,
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

    username = context.args[0].strip()

    if not username.startswith("@"):
        username = "@" + username

    await update.message.reply_text(
        "🔎 Vérification du canal en cours..."
    )

    try:

        chat = await telegram_service.get_chat(
            username
        )

        member = await telegram_service.get_chat_member(
            username,
            update.effective_user.id,
        )

        bot_info = await telegram_service.get_me()

        bot_id = bot_info.get("id")

        if not bot_id:
            raise RuntimeError(
                "Impossible de récupérer l'identifiant du bot."
            )

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
    # PROPRIÉTAIRE DU CANAL
    # ========================================================

    owner_ok = (
        member.get("status") == "creator"
    )

    # ========================================================
    # BOT ADMINISTRATEUR
    # ========================================================

    bot_status = bot_member.get("status")

    bot_admin = bot_status in {
        "administrator",
        "creator",
    }

    title = chat.get("title") or username

    subscribers = chat.get(
        "member_count",
        "—",
    )

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

        labels = {
            "pending_payment": "Paiement en attente",
            "waiting_admin": "Fonds réservés - en attente d'un administrateur",
            "transfer_started": "Transfert du canal en cours",
            "protection_period": "Période de protection",
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
        "<b>/addadmin TELEGRAM_ID</b> — ajouter un admin (principal seulement)\n"
        "<b>/removeadmin TELEGRAM_ID</b> — retirer un admin (principal seulement)\n"
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

async def extra_stats(db) -> tuple[int, int]:
    """(canaux où le bot est administrateur, annonces en ligne)."""

    bot_channels = await db.scalar(
        select(func.count())
        .select_from(BotChat)
        .where(
            BotChat.bot_status == "administrator",
            BotChat.chat_type == "channel",
        )
    )

    live_listings = await db.scalar(
        select(func.count())
        .select_from(Listing)
        .where(Listing.status == "published")
    )

    return bot_channels or 0, live_listings or 0


async def my_chat_member_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Le bot a été ajouté / promu / retiré d'un canal ou d'un groupe.

    Sans ce gestionnaire, rien n'était enregistré : les statistiques
    n'augmentaient jamais quand on ajoutait le bot à un canal.
    """

    event = update.my_chat_member

    if event is None or event.chat.type not in (
        "channel",
        "supergroup",
        "group",
    ):
        return

    chat = event.chat
    new_status = event.new_chat_member.status
    actor = event.from_user.id if event.from_user else None

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(BotChat).where(
                    BotChat.telegram_chat_id == chat.id
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = BotChat(
                telegram_chat_id=chat.id,
                chat_type=chat.type,
                added_by_telegram_id=actor,
                bot_status=new_status,
            )
            db.add(row)

        row.chat_type = chat.type
        row.title = chat.title
        row.username = chat.username
        row.bot_status = new_status

        if new_status == "administrator" and actor:
            row.added_by_telegram_id = actor

        # Met à jour un canal déjà soumis dans l'application.
        channel = (
            await db.execute(
                select(Channel).where(
                    Channel.telegram_channel_id == chat.id
                )
            )
        ).scalar_one_or_none()

        if channel is not None:
            member = event.new_chat_member
            is_admin = new_status == "administrator"

            channel.bot_is_admin = is_admin
            channel.bot_permissions_verified = bool(
                is_admin
                and getattr(member, "can_manage_chat", False)
                and getattr(member, "can_invite_users", False)
            )

        await db.commit()

    logger.info(
        "Bot : %s dans %s (%s) -> %s",
        chat.type,
        chat.title,
        chat.id,
        new_status,
    )

    # Prévient la personne qui a ajouté le bot, ET vérifie ses droits.
    if new_status == "administrator" and chat.type == "channel" and actor:
        member = event.new_chat_member

        required = (
            ("can_manage_chat", "gérer le canal"),
            ("can_invite_users", "inviter des utilisateurs"),
        )

        missing = [
            label
            for attribute, label in required
            if not getattr(member, attribute, False)
        ]

        if missing:
            text = (
                f"⚠️ NexMarket est administrateur de « {chat.title} » "
                "mais il lui manque le droit de : "
                + ", ".join(missing)
                + ".\n\nActivez-le (Canal → Administrateurs → NexMarket), "
                "puis ouvrez l'application → Vendre."
            )
        else:
            text = (
                f"✅ NexMarket est administrateur de « {chat.title} » "
                "avec tous les droits nécessaires.\n\n"
                "Ouvrez l'application → Vendre : votre canal apparaît "
                "dans « Canaux détectés »."
            )

        try:
            await context.bot.send_message(chat_id=actor, text=text)
        except Exception:
            pass


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
        bot_channels, live_listings = await extra_stats(db)

    text = (
        "📊 <b>Statistiques NexMarket</b>\n\n"
        f"👥 Utilisateurs : <b>{users_count or 0}</b>\n"
        f"🟢 Utilisateurs actifs : <b>{active_users or 0}</b>\n"
        f"📢 Canaux soumis : <b>{channels_count or 0}</b>\n"
        f"🤖 Canaux où le bot est admin : <b>{bot_channels}</b>\n"
        f"🛍️ Annonces en ligne : <b>{live_listings}</b>\n"
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
# /ADDADMIN  /REMOVEADMIN  (administrateur principal uniquement)
# ============================================================

async def _primary_admin_required(update: Update) -> bool:
    if not await admin_required(update):
        return False

    if (
        not settings.ADMIN_TELEGRAM_ID
        or update.effective_user.id != settings.ADMIN_TELEGRAM_ID
    ):
        await update.message.reply_text(
            "⛔ Seul l'administrateur principal peut ajouter ou "
            "retirer des administrateurs."
        )
        return False

    return True


async def _set_admin(update: Update, context, make_admin: bool) -> None:
    if not await _primary_admin_required(update):
        return

    name = "addadmin" if make_admin else "removeadmin"

    if not context.args:
        await update.message.reply_text(
            f"Utilisation : <code>/{name} TELEGRAM_ID</code>\n\n"
            "La personne doit avoir envoyé /start au bot.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Le Telegram ID doit être un nombre.")
        return

    if not make_admin and telegram_id == settings.ADMIN_TELEGRAM_ID:
        await update.message.reply_text(
            "❌ L'administrateur principal ne peut pas être retiré."
        )
        return

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one_or_none()

        if not user:
            await update.message.reply_text(
                "❌ Utilisateur introuvable : il doit d'abord envoyer /start au bot."
            )
            return

        user.is_admin = make_admin

        if make_admin:
            user.is_active = True

        await db.commit()

        await update.message.reply_text(
            ("👑 <b>Administrateur ajouté.</b>" if make_admin
             else "✅ <b>Administrateur retiré.</b>")
            + f"\n\nTelegram ID : <code>{telegram_id}</code>\n"
            f"NEXA ID : <code>{user.nexa_id}</code>",
            parse_mode=ParseMode.HTML,
        )


async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_admin(update, context, True)


async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_admin(update, context, False)


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
        "Envoie maintenant le message que tu veux envoyer aux "
        "utilisateurs actifs : un texte, ou une <b>photo avec sa légende</b>.\n"
        "La mise en forme (gras, italique, liens) est conservée. Les emojis "
        "animés Premium peuvent s'afficher comme des emojis normaux : "
        "c'est une limite de Telegram pour les bots.\n\n"
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
# BROADCAST MESSAGE
# ============================================================

async def _broadcast_one(bot, telegram_id: int, source) -> None:
    """Envoie le message de l'admin (texte OU photo + légende) à un utilisateur.

    copy_message conserve la photo et la mise en forme (gras, italique, liens,
    spoilers). Si Telegram refuse la copie (BadRequest : ex. emoji Premium non
    autorisé pour un bot), on renvoie une version simple : photo + texte brut.
    Les autres erreurs (utilisateur ayant bloqué le bot...) remontent : échec compté.
    """

    try:
        await bot.copy_message(
            chat_id=telegram_id,
            from_chat_id=source.chat_id,
            message_id=source.message_id,
        )
    except BadRequest:
        if source.photo:
            await bot.send_photo(
                chat_id=telegram_id,
                photo=source.photo[-1].file_id,
                caption=(source.caption or "")[:1000] or None,
            )
        else:
            await bot.send_message(
                chat_id=telegram_id,
                text=source.text or source.caption,
            )


async def broadcast_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message or not update.effective_user:
        return

    if not context.user_data.get("waiting_broadcast"):
        return

    if not await is_admin_user(
        update.effective_user.id
    ):

        context.user_data.pop(
            "waiting_broadcast",
            None,
        )

        await update.message.reply_text(
            "⛔ Accès refusé."
        )

        return

    context.user_data.pop(
        "waiting_broadcast",
        None,
    )

    source = update.message
    message = source.text or source.caption
    has_photo = bool(source.photo)

    if not message and not has_photo:

        await update.message.reply_text(
            "❌ Le message est vide."
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

            await _broadcast_one(context.bot, telegram_id, source)

            sent += 1

        except Exception as exc:

            failed += 1

            logger.warning(
                "Broadcast impossible vers %s : %s",
                telegram_id,
                exc,
            )

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "✅ <b>Diffusion terminée</b>\n\n"
        f"📨 Envoyés : <b>{sent}</b>\n"
        f"❌ Échecs : <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
    )

    # Le message de diffusion ne doit PAS aussi partir dans une discussion de
    # transaction ouverte par l'admin (groupe suivant).
    raise ApplicationHandlerStop



# ============================================================
# DISCUSSION D'UNE TRANSACTION (acheteur / vendeur / admin)
# ============================================================
# Les messages écrits dans la Mini App ou la console admin arrivent ici
# via le bot. Le bouton « Répondre » (ou une réponse Telegram directe au
# message) renvoie le texte dans la même discussion.

CHAT_TAG = re.compile(r"Discussion #(\d+)")


async def _load_chat_context(telegram_id: int, transaction_id: int):
    """Retourne (user, transaction, erreur)."""

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
        ).scalar_one_or_none()

        if user is None:
            return None, None, (
                "Ouvre d'abord la Mini App (ou la console admin) une fois "
                "pour activer ton compte, puis réessaie."
            )

        if not user.is_active:
            return None, None, "⛔ Ton compte est désactivé."

        transaction = (
            await db.execute(
                select(Transaction).where(Transaction.id == transaction_id)
            )
        ).scalar_one_or_none()

        if transaction is None or role_for(transaction, user) is None:
            return None, None, "❌ Discussion introuvable."

        return user, transaction, None


async def stop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not update.message:
        return

    had_chat = context.user_data.pop("chat_tx", None)

    await update.message.reply_text(
        "✅ Discussion quittée. Utilise « Répondre » sous un message "
        "pour la rouvrir."
        if had_chat
        else "ℹ️ Aucune discussion ouverte."
    )


async def approve_transfer_callback(query) -> None:
    """Bouton « ✅ Autoriser le transfert » : l'ACCORD de l'administrateur.

    Seul un administrateur peut cliquer ; c'est lui (jamais l'assistant IA) qui
    fait passer la transaction à « transfert commencé ».
    """

    try:
        transaction_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    if not await is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ Réservé aux administrateurs.")
        return

    from app.services.transaction_service import (
        TransactionService,
        TransactionServiceError,
    )

    async with AsyncSessionLocal() as db:
        try:
            transaction = await TransactionService(db).start_transfer(transaction_id)
        except TransactionServiceError as exc:
            await query.message.reply_text(f"❌ {exc}")
            return

        if not transaction.assigned_admin_id:
            admin = (
                await db.execute(
                    select(User).where(User.telegram_id == query.from_user.id)
                )
            ).scalar_one_or_none()
            if admin:
                transaction.assigned_admin_id = admin.id
                await db.commit()

    await query.message.reply_text(
        f"✅ Transfert autorisé pour la transaction #{transaction_id}. "
        "L'assistant guide maintenant le vendeur ; marquez le transfert comme "
        "terminé depuis la console quand vous l'avez constaté."
    )


async def open_chat_callback(query, context) -> None:

    try:
        transaction_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    user, transaction, error = await _load_chat_context(
        query.from_user.id,
        transaction_id,
    )

    if error:
        await query.message.reply_text(error)
        return

    context.user_data["chat_tx"] = transaction.id

    role = ROLE_LABELS.get(role_for(transaction, user), "")

    await query.message.reply_text(
        f"✍️ Discussion #{transaction.id} · {transaction.reference}\n"
        f"Tu écris en tant que : {role}.\n\n"
        "Envoie ton message : il sera transmis aux autres participants.\n"
        "/stop pour quitter la discussion."
    )


async def chat_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    message = update.message

    if not message or not update.effective_user:
        return

    # Capture d'écran / image envoyée dans la discussion (ex. preuve du transfert du canal).
    attachment_file_id = None
    attachment_type = "text"

    if message.photo:
        attachment_file_id = message.photo[-1].file_id  # la plus grande taille
        attachment_type = "image"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        attachment_file_id = message.document.file_id
        attachment_type = "document"

    if attachment_file_id is None and not message.text:
        return

    if context.user_data.get("waiting_broadcast"):
        return

    transaction_id = None

    # 1) Réponse Telegram directe à un message de discussion.
    replied = message.reply_to_message

    if replied and (replied.text or replied.caption):
        match = CHAT_TAG.search(replied.text or replied.caption or "")

        if match:
            transaction_id = int(match.group(1))

    # 2) Discussion ouverte avec le bouton « Répondre ».
    if transaction_id is None:
        transaction_id = context.user_data.get("chat_tx")

    if not transaction_id:
        return

    text = (message.text or message.caption or "").strip()

    if attachment_file_id is not None and not text:
        # Texte visible dans la discussion (et lu par l'assistant, qui ne voit pas l'image).
        text = "📷 Capture d'écran envoyée."

    if not text:
        return

    if len(text) > 5000:
        await message.reply_text(
            "❌ Message trop long (5000 caractères maximum)."
        )
        return

    user, transaction, error = await _load_chat_context(
        update.effective_user.id,
        int(transaction_id),
    )

    if error:
        context.user_data.pop("chat_tx", None)
        await message.reply_text(error)
        return

    async with AsyncSessionLocal() as db:
        tx = (
            await db.execute(
                select(Transaction).where(Transaction.id == transaction.id)
            )
        ).scalar_one()

        sender = (
            await db.execute(select(User).where(User.id == user.id))
        ).scalar_one()

        await post_message(
            db,
            tx,
            sender,
            text,
            message_type=attachment_type,
            attachment_file_id=attachment_file_id,
        )

    context.user_data["chat_tx"] = int(transaction_id)

    await message.reply_text(
        "✅ Capture envoyée." if attachment_file_id else "✅ Message envoyé."
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

    if query.data and query.data.startswith("assist_ok:"):
        if query.from_user:
            await approve_transfer_callback(query)
        return

    if query.data and query.data.startswith("chat:"):
        if query.from_user:
            await open_chat_callback(query, context)
        return

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

        if not await is_admin_user(
            query.from_user.id
        ):

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
                select(func.count())
                .select_from(Transaction)
            )

            bot_channels, live_listings = await extra_stats(db)

        await query.message.reply_text(
            "📊 <b>Statistiques NexMarket</b>\n\n"
            f"👥 Utilisateurs : <b>{users_count or 0}</b>\n"
            f"🟢 Actifs : <b>{active_users or 0}</b>\n"
            f"📢 Canaux soumis : <b>{channels_count or 0}</b>\n"
            f"🤖 Canaux où le bot est admin : <b>{bot_channels}</b>\n"
            f"🛍️ Annonces en ligne : <b>{live_listings}</b>\n"
            f"💼 Transactions : <b>{transactions_count or 0}</b>",
            parse_mode=ParseMode.HTML,
        )

    elif query.data == "admin_users":

        if not query.from_user:
            return

        if not await is_admin_user(
            query.from_user.id
        ):

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

        if not await is_admin_user(
            query.from_user.id
        ):

            await query.message.reply_text(
                "⛔ Accès refusé."
            )
            return

        context.user_data[
            "waiting_broadcast"
        ] = True

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

# Types de mises à jour réellement utilisés par le bot.
BOT_ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


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
        .connect_timeout(10)
        .read_timeout(15)
        .write_timeout(15)
        .pool_timeout(10)
        .get_updates_read_timeout(35)
        .build()
    )

    # Canal obligatoire : exécuté avant toutes les commandes / boutons.
    application.add_handler(
        TypeHandler(Update, subscription_gate),
        group=-1,
    )

    # Bot ajouté / promu / retiré d'un canal (alimente les statistiques).
    application.add_handler(
        ChatMemberHandler(
            my_chat_member_handler,
            ChatMemberHandler.MY_CHAT_MEMBER,
        )
    )

    # --------------------------------------------------------
    # UTILISATEURS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            ["retrait", "retraits", "withdraw"],
            withdraw_help_command,
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
    # ADMIN
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
            "addadmin",
            addadmin_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "removeadmin",
            removeadmin_command,
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
            (filters.TEXT & ~filters.COMMAND) | filters.PHOTO,
            broadcast_message_handler,
        )
    )

    # --------------------------------------------------------
    # DISCUSSION DE TRANSACTION
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "stop",
            stop_command,
        )
    )

    # Groupe 1 : s'exécute en plus du handler de diffusion (groupe 0).
    application.add_handler(
        MessageHandler(
            (
                (filters.TEXT & ~filters.COMMAND)
                | filters.PHOTO
                | filters.Document.IMAGE
            )
            & filters.ChatType.PRIVATE,
            chat_message_handler,
        ),
        group=1,
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
    # ERRORS
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
        drop_pending_updates=True,
        allowed_updates=BOT_ALLOWED_UPDATES,
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()