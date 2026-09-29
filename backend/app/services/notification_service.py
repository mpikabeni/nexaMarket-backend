from __future__ import annotations

from app.services.telegram_service import TelegramService


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
