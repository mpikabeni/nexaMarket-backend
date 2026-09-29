from __future__ import annotations

from dataclasses import dataclass

from telegram import Bot
from telegram.error import TelegramError
from telegram.constants import ChatMemberStatus

from app.config import settings


@dataclass
class TelegramChannelVerification:
    channel_id: int
    title: str | None
    username: str | None
    photo_url: str | None
    subscriber_count: int
    owner_verified: bool
    bot_is_admin: bool
    bot_permissions_verified: bool
    submitted_by_owner: bool
    error: str | None = None


class TelegramService:
    """
    Service centralisé pour les opérations Telegram de NexMarket.
    """

    REQUIRED_ADMIN_PERMISSIONS = {
        "can_manage_chat": True,
        "can_post_messages": True,
        "can_edit_messages": True,
        "can_delete_messages": True,
        "can_invite_users": True,
    }

    def __init__(self) -> None:
        self.bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN,
        )

    async def close(self) -> None:
        """
        Ferme proprement la session HTTP du bot.
        """
        await self.bot.shutdown()

    async def get_channel(self, channel_id: int):
        """
        Récupère les informations publiques du canal.
        """

        try:
            return await self.bot.get_chat(
                chat_id=channel_id,
            )
        except TelegramError as exc:
            raise ValueError(
                f"Impossible d'accéder au canal Telegram : {exc}"
            ) from exc

    async def get_member(
        self,
        channel_id: int,
        telegram_user_id: int,
    ):
        """
        Récupère le statut d'un utilisateur dans le canal.
        """

        try:
            return await self.bot.get_chat_member(
                chat_id=channel_id,
                user_id=telegram_user_id,
            )
        except TelegramError as exc:
            raise ValueError(
                f"Impossible de vérifier le membre Telegram : {exc}"
            ) from exc

    async def verify_bot_admin(
        self,
        channel_id: int,
    ) -> tuple[bool, bool]:
        """
        Vérifie que le bot est administrateur du canal et
        possède les permissions nécessaires.

        Retourne :
            (bot_is_admin, permissions_ok)
        """

        me = await self.bot.get_me()

        try:
            member = await self.bot.get_chat_member(
                chat_id=channel_id,
                user_id=me.id,
            )
        except TelegramError:
            return False, False

        if member.status not in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }:
            return False, False

        # Le propriétaire possède naturellement les droits
        # nécessaires. Pour un administrateur, on vérifie
        # explicitement les permissions.
        if member.status == ChatMemberStatus.OWNER:
            return True, True

        permissions_ok = all(
            getattr(member, permission, False) is True
            for permission in self.REQUIRED_ADMIN_PERMISSIONS
        )

        return True, permissions_ok

    async def verify_channel_owner(
        self,
        channel_id: int,
        telegram_user_id: int,
    ) -> bool:
        """
        Vérifie que l'utilisateur qui soumet le canal est
        réellement le propriétaire Telegram.

        Un simple administrateur n'est PAS considéré comme
        propriétaire.
        """

        try:
            member = await self.bot.get_chat_member(
                chat_id=channel_id,
                user_id=telegram_user_id,
            )
        except TelegramError:
            return False

        return member.status == ChatMemberStatus.OWNER

    async def get_subscriber_count(
        self,
        channel_id: int,
    ) -> int:
        """
        Récupère le nombre actuel d'abonnés du canal.
        """

        try:
            return await self.bot.get_chat_member_count(
                chat_id=channel_id,
            )
        except TelegramError:
            return 0

    async def verify_channel_submission(
        self,
        channel_id: int,
        submitted_by_telegram_id: int,
    ) -> TelegramChannelVerification:
        """
        Vérification complète avant soumission d'un canal.

        Conditions principales :
        1. Le canal doit être accessible au bot.
        2. Le bot doit être administrateur.
        3. Le bot doit avoir les permissions nécessaires.
        4. Le demandeur doit être le propriétaire du canal.
        """

        try:
            chat = await self.get_channel(channel_id)

            bot_is_admin, permissions_ok = (
                await self.verify_bot_admin(channel_id)
            )

            owner_verified = await self.verify_channel_owner(
                channel_id,
                submitted_by_telegram_id,
            )

            subscriber_count = await self.get_subscriber_count(
                channel_id,
            )

            return TelegramChannelVerification(
                channel_id=channel_id,
                title=chat.title,
                username=getattr(chat, "username", None),
                photo_url=None,
                subscriber_count=subscriber_count,
                owner_verified=owner_verified,
                bot_is_admin=bot_is_admin,
                bot_permissions_verified=permissions_ok,
                submitted_by_owner=owner_verified,
            )

        except ValueError as exc:
            return TelegramChannelVerification(
                channel_id=channel_id,
                title=None,
                username=None,
                photo_url=None,
                subscriber_count=0,
                owner_verified=False,
                bot_is_admin=False,
                bot_permissions_verified=False,
                submitted_by_owner=False,
                error=str(exc),
            )

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
    ):
        """
        Envoie un message via le bot.
        """

        return await self.bot.send_message(
            chat_id=chat_id,
            text=text,
        )

    async def send_transaction_message(
        self,
        telegram_user_id: int,
        text: str,
    ):
        """
        Envoie une notification privée à un utilisateur.
        """

        return await self.send_message(
            chat_id=telegram_user_id,
            text=text,
        )
