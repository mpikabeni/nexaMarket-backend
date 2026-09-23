from __future__ import annotations

import logging
from typing import Optional

from app.services.telegram_service import (
    TelegramServiceError,
    telegram_service,
)


logger = logging.getLogger(__name__)


class NotificationService:
    """
    Notifications Telegram de NexMarket.

    Ce service centralise les messages envoyés :
    - à l'acheteur ;
    - au vendeur ;
    - aux administrateurs ;
    - lors des différentes étapes d'une transaction.
    """

    # =========================================================
    # MESSAGE GENERIQUE
    # =========================================================

    async def send(
        self,
        telegram_id: int | str,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> bool:

        try:
            await telegram_service.send_message(
                chat_id=telegram_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )

            return True

        except TelegramServiceError as exc:
            logger.warning(
                "Notification Telegram impossible pour %s : %s",
                telegram_id,
                exc,
            )

            return False

    # =========================================================
    # VENDEUR : ANNONCE VALIDEE
    # =========================================================

    async def listing_approved(
        self,
        telegram_id: int,
        channel_name: str,
    ) -> bool:

        text = (
            "✅ <b>Annonce validée</b>\n\n"
            f"Votre annonce pour "
            f"<b>{self._escape(channel_name)}</b> "
            "a été validée par NexMarket.\n\n"
            "Elle est maintenant visible sur la marketplace."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # VENDEUR : ANNONCE REFUSEE
    # =========================================================

    async def listing_rejected(
        self,
        telegram_id: int,
        channel_name: str,
        reason: Optional[str] = None,
    ) -> bool:

        text = (
            "❌ <b>Annonce refusée</b>\n\n"
            f"L'annonce pour "
            f"<b>{self._escape(channel_name)}</b> "
            "n'a pas été publiée."
        )

        if reason:
            text += (
                "\n\n"
                f"<b>Motif :</b> "
                f"{self._escape(reason)}"
            )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # ACHETEUR : PAIEMENT
    # =========================================================

    async def payment_pending(
        self,
        telegram_id: int,
        transaction_reference: str,
        checkout_url: Optional[str] = None,
    ) -> bool:

        text = (
            "💳 <b>Paiement en attente</b>\n\n"
            f"Transaction : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "Votre paiement Money Fusion est en attente."
        )

        keyboard = None

        if checkout_url:
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "💳 Payer maintenant",
                            "url": checkout_url,
                        }
                    ]
                ]
            }

        return await self.send(
            telegram_id,
            text,
            reply_markup=keyboard,
        )

    # =========================================================
    # ACHETEUR : PAIEMENT CONFIRME
    # =========================================================

    async def payment_confirmed(
        self,
        telegram_id: int,
        transaction_reference: str,
    ) -> bool:

        text = (
            "✅ <b>Paiement confirmé</b>\n\n"
            f"Transaction : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "Les fonds sont maintenant sécurisés "
            "et la transaction va être prise en charge "
            "par NexMarket."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # VENDEUR : NOUVEL ACHAT
    # =========================================================

    async def seller_new_transaction(
        self,
        telegram_id: int,
        transaction_reference: str,
        channel_name: str,
        amount: float,
    ) -> bool:

        text = (
            "🛒 <b>Nouvelle transaction</b>\n\n"
            f"Canal : <b>{self._escape(channel_name)}</b>\n"
            f"Montant : <b>{amount:,.0f} XAF</b>\n"
            f"Référence : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "Le paiement de l'acheteur a été confirmé. "
            "Un administrateur NexMarket va prendre "
            "la transaction en charge."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # ACHETEUR / VENDEUR : ADMIN ASSIGNE
    # =========================================================

    async def transaction_assigned(
        self,
        telegram_id: int,
        transaction_reference: str,
        admin_name: Optional[str] = None,
    ) -> bool:

        if admin_name:
            admin_text = (
                f"L'administrateur <b>"
                f"{self._escape(admin_name)}</b> "
                "prend maintenant la transaction en charge."
            )
        else:
            admin_text = (
                "Un administrateur NexMarket "
                "prend maintenant la transaction en charge."
            )

        text = (
            "👤 <b>Transaction prise en charge</b>\n\n"
            f"Référence : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            f"{admin_text}\n\n"
            "Vous pouvez suivre les prochaines étapes "
            "depuis votre transaction."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # TRANSFERT EN COURS
    # =========================================================

    async def transfer_started(
        self,
        telegram_id: int,
        transaction_reference: str,
    ) -> bool:

        text = (
            "🔄 <b>Transfert en cours</b>\n\n"
            f"Transaction : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "L'administrateur NexMarket accompagne "
            "les parties pour effectuer le transfert "
            "du canal via Telegram."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # TRANSACTION TERMINEE
    # =========================================================

    async def transaction_completed(
        self,
        telegram_id: int,
        transaction_reference: str,
    ) -> bool:

        text = (
            "🎉 <b>Transaction terminée</b>\n\n"
            f"Référence : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "La transaction NexMarket est terminée."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # TRANSACTION ANNULEE
    # =========================================================

    async def transaction_cancelled(
        self,
        telegram_id: int,
        transaction_reference: str,
        reason: Optional[str] = None,
    ) -> bool:

        text = (
            "⚠️ <b>Transaction annulée</b>\n\n"
            f"Référence : "
            f"<code>{self._escape(transaction_reference)}</code>"
        )

        if reason:
            text += (
                "\n\n"
                f"<b>Motif :</b> "
                f"{self._escape(reason)}"
            )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # LITIGE
    # =========================================================

    async def transaction_disputed(
        self,
        telegram_id: int,
        transaction_reference: str,
    ) -> bool:

        text = (
            "⚠️ <b>Litige ouvert</b>\n\n"
            f"Transaction : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "La transaction est maintenant examinée "
            "par l'équipe NexMarket."
        )

        return await self.send(
            telegram_id,
            text,
        )

    # =========================================================
    # ADMIN : NOUVELLE TRANSACTION
    # =========================================================

    async def admin_new_transaction(
        self,
        admin_telegram_id: int,
        transaction_reference: str,
        channel_name: str,
        amount: float,
    ) -> bool:

        text = (
            "🔔 <b>Nouvelle transaction à traiter</b>\n\n"
            f"Canal : <b>{self._escape(channel_name)}</b>\n"
            f"Montant : <b>{amount:,.0f} XAF</b>\n"
            f"Référence : "
            f"<code>{self._escape(transaction_reference)}</code>\n\n"
            "Un administrateur peut prendre cette "
            "transaction en charge."
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "👤 Prendre en charge",
                        "callback_data": (
                            f"take_transaction:"
                            f"{transaction_reference}"
                        ),
                    }
                ]
            ]
        }

        return await self.send(
            admin_telegram_id,
            text,
            reply_markup=keyboard,
        )

    # =========================================================
    # ADMIN : LITIGE
    # =========================================================

    async def admin_dispute(
        self,
        admin_telegram_id: int,
        transaction_reference: str,
        reason: Optional[str] = None,
    ) -> bool:

        text = (
            "🚨 <b>Nouveau litige</b>\n\n"
            f"Transaction : "
            f"<code>{self._escape(transaction_reference)}</code>"
        )

        if reason:
            text += (
                "\n\n"
                f"<b>Motif :</b> "
                f"{self._escape(reason)}"
            )

        return await self.send(
            admin_telegram_id,
            text,
        )

    # =========================================================
    # ADMIN : VERIFICATION CANAL
    # =========================================================

    async def admin_channel_verification(
        self,
        admin_telegram_id: int,
        channel_name: str,
        seller_telegram_id: int,
    ) -> bool:

        text = (
            "🔎 <b>Nouveau canal à vérifier</b>\n\n"
            f"Canal : <b>{self._escape(channel_name)}</b>\n"
            f"Vendeur : "
            f"<code>{seller_telegram_id}</code>\n\n"
            "La vérification du canal doit être "
            "effectuée avant sa publication."
        )

        return await self.send(
            admin_telegram_id,
            text,
        )

    # =========================================================
    # UTILITAIRE : ECHAPPER HTML
    # =========================================================

    @staticmethod
    def _escape(value: object) -> str:
        """
        Echappe les caractères HTML utilisés par Telegram.
        """

        text = str(value or "")

        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )


# =============================================================
# INSTANCE UNIQUE
# =============================================================

notification_service = NotificationService()