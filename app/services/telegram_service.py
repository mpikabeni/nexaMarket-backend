
from __future__ import annotations

from dataclasses import dataclass

import asyncio

from telegram import Bot
from telegram.request import HTTPXRequest
from telegram.error import TelegramError
from telegram.constants import ChatMemberStatus

from app.config import settings


class TelegramServiceError(Exception):
    """
    Erreur dédiée aux opérations Telegram de NexMarket.
    """

    pass


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

    # Le bot ne publie rien dans le canal : il lui faut seulement être
    # administrateur (pour lire les membres / le nombre d'abonnés) et
    # pouvoir inviter. Avant, 5 droits étaient exigés (publier, modifier,
    # supprimer...), et le moindre oubli donnait un « échec » sans détail.
    REQUIRED_ADMIN_PERMISSIONS = {
        "can_manage_chat": True,
        "can_invite_users": True,
    }

    PERMISSION_LABELS = {
        "can_manage_chat": "gérer le canal",
        "can_invite_users": "inviter des utilisateurs",
    }

    def __init__(self) -> None:
        self.bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN,
            request=HTTPXRequest(
                connection_pool_size=8,
                connect_timeout=8.0,
                read_timeout=12.0,
                write_timeout=12.0,
                pool_timeout=5.0,
            ),
        )

    async def _get_me(self):
        """Identité du bot, demandée à Telegram une seule fois."""

        if getattr(self, "_me", None) is None:
            self._me = await self.bot.get_me()

        return self._me

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
            raise TelegramServiceError(
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
            raise TelegramServiceError(
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

        try:
            me = await self._get_me()

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
        # nécessaires.
        if member.status == ChatMemberStatus.OWNER:
            return True, True

        permissions_ok = all(
            getattr(member, permission, False) is True
            for permission in self.REQUIRED_ADMIN_PERMISSIONS
        )

        return True, permissions_ok

    async def get_missing_permissions(self, channel_id: int) -> list[str]:
        """Noms lisibles des droits d'administrateur qui manquent au bot."""

        try:
            me = await self._get_me()
            member = await self.bot.get_chat_member(
                chat_id=channel_id,
                user_id=me.id,
            )
        except TelegramError:
            return []

        if member.status == ChatMemberStatus.OWNER:
            return []

        return [
            self.PERMISSION_LABELS.get(permission, permission)
            for permission in self.REQUIRED_ADMIN_PERMISSIONS
            if getattr(member, permission, False) is not True
        ]

    async def fetch_photo(self, file_id: str) -> bytes | None:
        """Télécharge une photo de canal (passe par le proxy de l'API)."""

        try:
            file = await self.bot.get_file(file_id)
            return bytes(await file.download_as_bytearray())
        except TelegramError:
            return None

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
            # Quatre appels indépendants : lancés ensemble (au lieu de
            # l'un après l'autre) pour diviser le temps d'attente.
            (
                chat,
                (bot_is_admin, permissions_ok),
                owner_verified,
                subscriber_count,
            ) = await asyncio.gather(
                self.get_channel(channel_id),
                self.verify_bot_admin(channel_id),
                self.verify_channel_owner(
                    channel_id,
                    submitted_by_telegram_id,
                ),
                self.get_subscriber_count(channel_id),
            )

            return TelegramChannelVerification(
                channel_id=channel_id,
                title=chat.title,
                username=getattr(chat, "username", None),
                photo_url=(
                    f"tg:{chat.photo.big_file_id}"
                    if getattr(chat, "photo", None)
                    else None
                ),
                subscriber_count=subscriber_count,
                owner_verified=owner_verified,
                bot_is_admin=bot_is_admin,
                bot_permissions_verified=permissions_ok,
                submitted_by_owner=owner_verified,
            )

        except TelegramServiceError as exc:
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

        try:
            return await self.bot.send_message(
                chat_id=chat_id,
                text=text,
            )
        except TelegramError as exc:
            raise TelegramServiceError(
                f"Impossible d'envoyer le message Telegram : {exc}"
            ) from exc

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


# ============================================================
# INSTANCE PARTAGÉE
# ============================================================
# Avant, chaque requête créait un nouveau Bot (donc une nouvelle
# session HTTP) qui n'était jamais fermé : fuite de connexions.

_shared_instance: TelegramService | None = None


def get_telegram_service() -> TelegramService:
    global _shared_instance

    if _shared_instance is None:
        _shared_instance = TelegramService()

    return _shared_instance
