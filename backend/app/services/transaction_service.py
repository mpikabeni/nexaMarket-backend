from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.services.jessikapay_service import (
    JessiKaPayError,
    JessiKaPayService,
)


class TransactionServiceError(Exception):
    """Erreur métier liée à une transaction NexMarket."""


class TransactionService:
    """
    Logique métier des transactions NexMarket.

    Flux principal :

        pending_payment
            ↓
        payment_confirmed
            ↓
        waiting_admin
            ↓
        assigned
            ↓
        transfer_pending
            ↓
        protection_period
            ↓
        completed
            ↓
        payout vendeur

    La commission NexMarket est de 5 %.
    """

    def __init__(
        self,
        db: AsyncSession,
        jessikapay: JessiKaPayService | None = None,
    ):
        self.db = db
        self.jessikapay = (
            jessikapay
            or JessiKaPayService()
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _reference(prefix: str) -> str:
        return (
            f"{prefix}-"
            f"{uuid4().hex[:16].upper()}"
        )

    async def _get_transaction(
        self,
        transaction_id: int,
    ) -> Transaction:
        result = await self.db.execute(
            select(Transaction).where(
                Transaction.id == transaction_id
            )
        )

        transaction = result.scalar_one_or_none()

        if transaction is None:
            raise TransactionServiceError(
                "Transaction introuvable."
            )

        return transaction

    async def _get_listing(
        self,
        listing_id: int,
    ) -> Listing:
        result = await self.db.execute(
            select(Listing).where(
                Listing.id == listing_id
            )
        )

        listing = result.scalar_one_or_none()

        if listing is None:
            raise TransactionServiceError(
                "Annonce introuvable."
            )

        return listing

    async def _get_wallet(
        self,
        user_id: int,
    ) -> Wallet:
        result = await self.db.execute(
            select(Wallet).where(
                Wallet.user_id == user_id
            )
        )

        wallet = result.scalar_one_or_none()

        if wallet is None:
            raise TransactionServiceError(
                "Wallet utilisateur introuvable."
            )

        return wallet

    # ========================================================
    # CREATE TRANSACTION
    # ========================================================

    async def create_transaction(
        self,
        *,
        buyer: User,
        listing_id: int,
    ) -> Transaction:
        """
        Crée une transaction pour une annonce publique.

        Le vendeur ne peut pas acheter sa propre annonce.
        """

        listing = await self._get_listing(
            listing_id
        )

        if not listing.is_public:
            raise TransactionServiceError(
                "Cette annonce n'est pas disponible."
            )

        if listing.status not in {
            "published",
        }:
            raise TransactionServiceError(
                "Cette annonce n'est pas disponible à l'achat."
            )

        if listing.seller_id == buyer.id:
            raise TransactionServiceError(
                "Vous ne pouvez pas acheter votre propre annonce."
            )

        platform_fee_rate = Decimal(
            str(listing.platform_fee_rate)
        )

        if platform_fee_rate < 0:
            raise TransactionServiceError(
                "Commission invalide."
            )

        channel_price = self._money(
            Decimal(str(listing.price))
        )

        platform_fee = self._money(
            channel_price * platform_fee_rate
        )

        seller_amount = self._money(
            channel_price - platform_fee
        )

        if seller_amount < 0:
            raise TransactionServiceError(
                "Montant vendeur invalide."
            )

        reference = self._reference(
            "NMX"
        )

        transaction = Transaction(
            reference=reference,
            listing_id=listing.id,
            buyer_id=buyer.id,
            seller_id=listing.seller_id,
            channel_price=channel_price,
            platform_fee=platform_fee,
            provider_fee=Decimal("0.00"),
            total_buyer_amount=channel_price,
            seller_amount=seller_amount,
            currency=listing.currency,
            platform_fee_rate=platform_fee_rate,
            status="pending_payment",
            payment_status="pending",
            escrow_held=False,
        )

        self.db.add(transaction)

        # Une annonce réservée ne peut plus être achetée
        # par plusieurs personnes en même temps.
        listing.status = "reserved"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # CREATE PAYMENT
    # ========================================================

    async def create_payment(
        self,
        *,
        transaction_id: int,
    ) -> dict:
        """
        Crée la demande de paiement JessiKaPay.

        IMPORTANT :
        Le montant envoyé à JessiKaPay doit être compatible
        avec le règlement de la devise utilisée par NexMarket.

        La documentation fournie ne définit pas de conversion
        XAF/XOF/USD/EUR. Cette méthode refuse donc les devises
        autres que XAF pour le paiement JessiKaPay actuel.
        """

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "pending_payment":
            raise TransactionServiceError(
                "Cette transaction n'attend plus de paiement."
            )

        if transaction.payment_reference:
            raise TransactionServiceError(
                "Une demande de paiement existe déjà."
            )

        if transaction.currency.upper() != "XAF":
            raise TransactionServiceError(
                "Le paiement JessiKaPay de cette version "
                "requiert une transaction en XAF."
            )

        amount = int(
            Decimal(
                str(transaction.total_buyer_amount)
            ).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )

        if amount <= 0:
            raise TransactionServiceError(
                "Montant de paiement invalide."
            )

        payment_reference = (
            f"NMX-PAY-{transaction.reference}"
        )

        try:
            response = await self.jessikapay.create_payment_request(
                jp_number=settings.NEXA_JP_NUMBER,
                amount=amount,
                reference=payment_reference,
                description=(
                    f"NexMarket transaction "
                    f"{transaction.reference}"
                ),
                expires_in_minutes=30,
            )
        except JessiKaPayError as exc:
            raise TransactionServiceError(
                str(exc)
            ) from exc

        transaction.payment_provider = "jessikapay"
        transaction.payment_reference = payment_reference
        transaction.payment_status = (
            response.get("status", "pending")
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return {
            "transaction_id": transaction.id,
            "reference": transaction.reference,
            "payment_reference": payment_reference,
            "amount": amount,
            "currency": transaction.currency,
            "status": transaction.payment_status,
            "request_id": response.get("request_id"),
            "code": response.get("code"),
            "payment_link": response.get("payment_link"),
            "expires_at": response.get("expires_at"),
        }

    # ========================================================
    # CONFIRM PAYMENT
    # ========================================================

    async def confirm_payment(
        self,
        *,
        transaction_id: int,
        provider_status: dict,
    ) -> Transaction:
        """
        Confirme un paiement uniquement lorsque JessiKaPay
        indique que celui-ci est réellement terminé.

        On ne considère jamais une simple création de
        payment-request comme un paiement confirmé.
        """

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status not in {
            "pending_payment",
        }:
            raise TransactionServiceError(
                "La transaction ne peut plus être confirmée."
            )

        status_value = str(
            provider_status.get("status", "")
        ).lower()

        if status_value not in {
            "completed",
            "paid",
        }:
            raise TransactionServiceError(
                "Le paiement JessiKaPay n'est pas confirmé."
            )

        transaction.payment_status = "completed"
        transaction.status = "payment_confirmed"
        transaction.payment_confirmed_at = (
            datetime.now(timezone.utc)
        )

        # ====================================================
        # ESCROW
        # ====================================================

        transaction.escrow_held = True
        transaction.escrow_held_at = (
            datetime.now(timezone.utc)
        )
        transaction.status = "waiting_admin"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # ASSIGN ADMIN
    # ========================================================

    async def assign_admin(
        self,
        *,
        transaction_id: int,
        admin: User,
    ) -> Transaction:
        if not admin.is_admin:
            raise TransactionServiceError(
                "Administrateur requis."
            )

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "waiting_admin":
            raise TransactionServiceError(
                "La transaction n'attend pas une assignation."
            )

        transaction.assigned_admin_id = admin.id
        transaction.status = "assigned"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # START CHANNEL TRANSFER
    # ========================================================

    async def start_transfer(
        self,
        *,
        transaction_id: int,
        admin: User,
    ) -> Transaction:
        if not admin.is_admin:
            raise TransactionServiceError(
                "Administrateur requis."
            )

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.assigned_admin_id != admin.id:
            raise TransactionServiceError(
                "Cet administrateur n'est pas assigné "
                "à cette transaction."
            )

        if transaction.status != "assigned":
            raise TransactionServiceError(
                "Le transfert ne peut pas commencer."
            )

        transaction.status = "transfer_pending"
        transaction.transfer_started_at = (
            datetime.now(timezone.utc)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # COMPLETE CHANNEL TRANSFER
    # ========================================================

    async def complete_transfer(
        self,
        *,
        transaction_id: int,
        admin: User,
    ) -> Transaction:
        """
        Enregistre que le transfert Telegram a été vérifié
        par l'administrateur.

        Cette méthode ne doit être appelée qu'après les
        vérifications Telegram réelles.
        """

        if not admin.is_admin:
            raise TransactionServiceError(
                "Administrateur requis."
            )

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.assigned_admin_id != admin.id:
            raise TransactionServiceError(
                "Cet administrateur n'est pas assigné "
                "à cette transaction."
            )

        if transaction.status != "transfer_pending":
            raise TransactionServiceError(
                "La transaction n'est pas en transfert."
            )

        now = datetime.now(timezone.utc)

        transaction.transfer_completed_at = now
        transaction.status = "protection_period"

        transaction.protection_ends_at = (
            now
            + timedelta(
                minutes=settings.ESCROW_PROTECTION_MINUTES
            )
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # FINISH PROTECTION
    # ========================================================

    async def finish_protection(
        self,
        *,
        transaction_id: int,
    ) -> Transaction:
        """
        Termine la période de protection.

        Le paiement vendeur n'est PAS effectué avant cette
        étape.
        """

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "protection_period":
            raise TransactionServiceError(
                "La transaction n'est pas en période de protection."
            )

        if not transaction.protection_ends_at:
            raise TransactionServiceError(
                "Date de fin de protection manquante."
            )

        now = datetime.now(timezone.utc)

        protection_end = transaction.protection_ends_at

        if protection_end.tzinfo is None:
            protection_end = protection_end.replace(
                tzinfo=timezone.utc
            )

        if now < protection_end:
            raise TransactionServiceError(
                "La période de protection n'est pas terminée."
            )

        transaction.status = "completed"
        transaction.buyer_confirmed_at = now

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # PAY SELLER
    # ========================================================

    async def payout_seller(
        self,
        *,
        transaction_id: int,
        seller_jp_number: str,
    ) -> dict:
        """
        Paie le vendeur après validation complète.

        Commission NexMarket :
            5 %

        Montant vendeur :
            95 %

        Le payout JessiKaPay est exécuté une seule fois.
        """

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "completed":
            raise TransactionServiceError(
                "La transaction n'est pas prête pour le paiement vendeur."
            )

        if transaction.seller_payout_reference:
            raise TransactionServiceError(
                "Le vendeur a déjà été payé ou un payout "
                "est déjà enregistré."
            )

        if transaction.currency.upper() != "XAF":
            raise TransactionServiceError(
                "Le payout JessiKaPay de cette version "
                "requiert une transaction en XAF."
            )

        amount = int(
            Decimal(
                str(transaction.seller_amount)
            ).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )

        if amount <= 0:
            raise TransactionServiceError(
                "Montant vendeur invalide."
            )

        payout_reference = (
            f"NMX-PAYOUT-{transaction.reference}"
        )

        try:
            response = await self.jessikapay.create_payout(
                jp_number=seller_jp_number,
                amount=amount,
                reference=payout_reference,
                description=(
                    f"NexMarket vendeur "
                    f"{transaction.reference}"
                ),
            )
        except JessiKaPayError as exc:
            raise TransactionServiceError(
                str(exc)
            ) from exc

        transaction.seller_payout_reference = (
            payout_reference
        )
        transaction.seller_paid_at = (
            datetime.now(timezone.utc)
        )

        transaction.nexmarket_fee_recorded_at = (
            datetime.now(timezone.utc)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return {
            "transaction_id": transaction.id,
            "reference": transaction.reference,
            "payout_reference": payout_reference,
            "seller_amount": amount,
            "currency": transaction.currency,
            "jessikapay": response,
        }

    # ========================================================
    # CANCEL
    # ========================================================

    async def cancel_transaction(
        self,
        *,
        transaction_id: int,
        admin: User,
        reason: str | None = None,
    ) -> Transaction:
        if not admin.is_admin:
            raise TransactionServiceError(
                "Administrateur requis."
            )

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status in {
            "completed",
            "refunded",
        }:
            raise TransactionServiceError(
                "Cette transaction ne peut plus être annulée."
            )

        transaction.status = "cancelled"
        transaction.cancelled_at = (
            datetime.now(timezone.utc)
        )

        if reason:
            transaction.admin_notes = reason

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ========================================================
    # DISPUTE
    # ========================================================

    async def open_dispute(
        self,
        *,
        transaction_id: int,
        user: User,
        reason: str,
    ) -> Transaction:
        transaction = await self._get_transaction(
            transaction_id
        )

        if user.id not in {
            transaction.buyer_id,
            transaction.seller_id,
        }:
            raise TransactionServiceError(
                "Vous ne participez pas à cette transaction."
            )

        if transaction.status in {
            "cancelled",
            "refunded",
        }:
            raise TransactionServiceError(
                "Cette transaction est déjà clôturée."
            )

        if transaction.status == "completed":
            raise TransactionServiceError(
                "Cette transaction est déjà terminée."
            )

        transaction.status = "disputed"
        transaction.dispute_reason = reason
        transaction.disputed_at = (
            datetime.now(timezone.utc)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction
