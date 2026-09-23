from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class TelegramServiceError(Exception):
    """Erreur générale du service Telegram."""


class TelegramService:
    """
    Service Telegram de NexMarket.

    Utilisé pour :
    - récupérer les informations d'un canal ;
    - vérifier que le bot est administrateur ;
    - vérifier le rôle d'un utilisateur ;
    - envoyer des messages ;
    - créer des liens d'invitation ;
    - vérifier un canal avant sa publication.

    IMPORTANT :
    Le bot ne transfère jamais la propriété d'un canal.
    Le transfert de propriété reste effectué par Telegram.
    """

    def __init__(self) -> None:
        self.base_url = ""

        token = (
            settings.TELEGRAM_BOT_TOKEN
            or ""
        ).strip()

        if token:
            self.base_url = (
                f"https://api.telegram.org/bot{token}"
            )

    # =========================================================
    # VERIFICATION DE CONFIGURATION
    # =========================================================

    def _require_token(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise TelegramServiceError(
                "TELEGRAM_BOT_TOKEN n'est pas configuré."
            )

    # =========================================================
    # APPEL TELEGRAM
    # =========================================================

    async def _request(
        self,
        method: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        self._require_token()

        url = f"{self.base_url}/{method}"

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
            ) as client:

                response = await client.post(
                    url,
                    json=data or {},
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

        except httpx.TimeoutException as exc:
            logger.exception(
                "Timeout Telegram sur %s",
                method,
            )

            raise TelegramServiceError(
                "Telegram n'a pas répondu à temps."
            ) from exc

        except httpx.RequestError as exc:
            logger.exception(
                "Erreur réseau Telegram sur %s",
                method,
            )

            raise TelegramServiceError(
                "Impossible de contacter Telegram."
            ) from exc

        if response.status_code >= 400:
            logger.error(
                "Telegram HTTP %s : %s",
                response.status_code,
                response.text[:1000],
            )

            raise TelegramServiceError(
                f"Telegram a retourné HTTP "
                f"{response.status_code}."
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise TelegramServiceError(
                "Telegram a retourné une réponse invalide."
            ) from exc

        if not isinstance(result, dict):
            raise TelegramServiceError(
                "Réponse Telegram invalide."
            )

        if not result.get("ok"):
            description = result.get(
                "description",
                "Erreur Telegram inconnue.",
            )

            raise TelegramServiceError(
                str(description)
            )

        return result

    # =========================================================
    # INFORMATIONS BOT
    # =========================================================

    async def get_me(self) -> dict[str, Any]:
        result = await self._request("getMe")

        return result.get("result", {})

    # =========================================================
    # INFORMATIONS D'UN CHAT / CANAL
    # =========================================================

    async def get_chat(
        self,
        chat_id: str | int,
    ) -> dict[str, Any]:

        result = await self._request(
            "getChat",
            {
                "chat_id": chat_id,
            },
        )

        return result.get("result", {})

    # =========================================================
    # MEMBRE D'UN CHAT
    # =========================================================

    async def get_chat_member(
        self,
        chat_id: str | int,
        user_id: int,
    ) -> dict[str, Any]:

        result = await self._request(
            "getChatMember",
            {
                "chat_id": chat_id,
                "user_id": user_id,
            },
        )

        return result.get("result", {})

    # =========================================================
    # ADMINISTRATEURS DU CANAL
    # =========================================================

    async def get_chat_administrators(
        self,
        chat_id: str | int,
    ) -> list[dict[str, Any]]:

        result = await self._request(
            "getChatAdministrators",
            {
                "chat_id": chat_id,
            },
        )

        administrators = result.get(
            "result",
            [],
        )

        if not isinstance(administrators, list):
            return []

        return administrators

    # =========================================================
    # NOMBRE D'ABONNES
    # =========================================================

    async def get_chat_member_count(
        self,
        chat_id: str | int,
    ) -> int:

        result = await self._request(
            "getChatMemberCount",
            {
                "chat_id": chat_id,
            },
        )

        count = result.get("result", 0)

        try:
            return int(count)
        except (TypeError, ValueError):
            return 0

    # =========================================================
    # VERIFIER LE BOT
    # =========================================================

    async def verify_bot_admin(
        self,
        chat_id: str | int,
    ) -> dict[str, Any]:

        bot = await self.get_me()

        bot_id = bot.get("id")

        if not bot_id:
            raise TelegramServiceError(
                "Impossible de récupérer l'identifiant du bot."
            )

        member = await self.get_chat_member(
            chat_id,
            int(bot_id),
        )

        status = member.get("status")

        is_admin = status in (
            "administrator",
            "creator",
        )

        return {
            "is_admin": is_admin,
            "status": status,
            "member": member,
            "bot_id": bot_id,
        }

    # =========================================================
    # VERIFIER LE VENDEUR
    # =========================================================

    async def verify_user_admin(
        self,
        chat_id: str | int,
        user_id: int,
    ) -> dict[str, Any]:

        member = await self.get_chat_member(
            chat_id,
            user_id,
        )

        status = member.get("status")

        is_admin = status in (
            "administrator",
            "creator",
        )

        is_owner = status == "creator"

        return {
            "is_admin": is_admin,
            "is_owner": is_owner,
            "status": status,
            "member": member,
        }

    # =========================================================
    # VERIFICATION COMPLETE DU CANAL
    # =========================================================

    async def verify_channel(
        self,
        chat_id: str | int,
        seller_telegram_id: int,
    ) -> dict[str, Any]:

        logger.info(
            "Vérification canal %s pour vendeur %s",
            chat_id,
            seller_telegram_id,
        )

        chat = await self.get_chat(chat_id)

        chat_type = chat.get("type")

        if chat_type != "channel":
            raise TelegramServiceError(
                "Le chat indiqué n'est pas un canal Telegram."
            )

        bot_check = await self.verify_bot_admin(
            chat_id
        )

        if not bot_check["is_admin"]:
            return {
                "verified": False,
                "reason": (
                    "Le bot NexMarket doit être "
                    "administrateur du canal."
                ),
                "chat": chat,
                "bot_is_admin": False,
                "seller_is_admin": False,
            }

        seller_check = await self.verify_user_admin(
            chat_id,
            seller_telegram_id,
        )

        if not seller_check["is_admin"]:
            return {
                "verified": False,
                "reason": (
                    "Le vendeur doit être "
                    "administrateur du canal."
                ),
                "chat": chat,
                "bot_is_admin": True,
                "seller_is_admin": False,
            }

        subscribers = 0

        try:
            subscribers = (
                await self.get_chat_member_count(
                    chat_id
                )
            )
        except TelegramServiceError:
            # Certaines informations peuvent être
            # temporairement indisponibles.
            logger.warning(
                "Impossible de récupérer le nombre "
                "d'abonnés du canal %s",
                chat_id,
            )

        username = chat.get("username")

        title = (
            chat.get("title")
            or "Canal Telegram"
        )

        return {
            "verified": True,
            "reason": "Canal vérifié avec succès.",
            "chat": chat,
            "chat_id": chat.get("id", chat_id),
            "title": title,
            "username": username,
            "description": chat.get(
                "description"
            ),
            "subscribers_count": subscribers,
            "bot_is_admin": True,
            "seller_is_admin": True,
            "seller_status": seller_check.get(
                "status"
            ),
        }

    # =========================================================
    # ENVOYER UN MESSAGE
    # =========================================================

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        reply_markup: Optional[dict] = None,
        parse_mode: Optional[str] = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:

        if not text:
            raise TelegramServiceError(
                "Le message Telegram ne peut pas être vide."
            )

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview":
                disable_web_page_preview,
        }

        if parse_mode:
            payload["parse_mode"] = parse_mode

        if reply_markup:
            payload["reply_markup"] = reply_markup

        result = await self._request(
            "sendMessage",
            payload,
        )

        return result.get("result", {})

    # =========================================================
    # MODIFIER UN MESSAGE
    # =========================================================

    async def edit_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> dict[str, Any]:

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        result = await self._request(
            "editMessageText",
            payload,
        )

        return result.get("result", {})

    # =========================================================
    # REPONDRE A UN CALLBACK
    # =========================================================

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:

        payload = {
            "callback_query_id":
                callback_query_id,
            "show_alert":
                show_alert,
        }

        if text:
            payload["text"] = text

        result = await self._request(
            "answerCallbackQuery",
            payload,
        )

        return bool(result.get("ok"))

    # =========================================================
    # LIEN D'INVITATION
    # =========================================================

    async def create_invite_link(
        self,
        chat_id: str | int,
        name: Optional[str] = None,
    ) -> Optional[str]:

        payload: dict[str, Any] = {
            "chat_id": chat_id,
        }

        if name:
            payload["name"] = name[:32]

        try:
            result = await self._request(
                "createChatInviteLink",
                payload,
            )

        except TelegramServiceError as exc:
            logger.warning(
                "Impossible de créer le lien "
                "d'invitation : %s",
                exc,
            )

            return None

        invite = result.get(
            "result",
            {},
        )

        return invite.get("invite_link")

    # =========================================================
    # VERIFICATION PAR USERNAME
    # =========================================================

    async def resolve_channel(
        self,
        username: str,
    ) -> dict[str, Any]:

        username = str(
            username or ""
        ).strip()

        if not username:
            raise TelegramServiceError(
                "Username du canal manquant."
            )

        if not username.startswith("@"):
            username = "@" + username

        chat = await self.get_chat(
            username
        )

        if chat.get("type") != "channel":
            raise TelegramServiceError(
                "Ce compte Telegram n'est pas un canal."
            )

        return chat


# =============================================================
# INSTANCE UNIQUE
# =============================================================

telegram_service = TelegramService()