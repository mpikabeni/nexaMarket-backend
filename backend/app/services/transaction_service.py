from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from secrets import token_hex

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.user import User
from app.services.jessikapay_service import (
    JessiKaPayError,
    JessiKaPayService,
)
from app.services.notification_service import NotificationService


class TransactionServiceError(Exception):
    """Erreur métier liée à une transaction."""


class TransactionService:
    def __init__(
        self,
        db: AsyncSession,
        jessikapay: JessiKaPayService | None = None,
    ):
        self.db = db
        self.jessikapay = jessikapay or JessiKaPayService()
        self.notifications = NotificationService()

    # ==========================================================
    # HELPERS
    # ==========================================================

    @staticmethod
    def _money(value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _reference(prefix: str) -> str:
        return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{token_hex(4).upper()}"

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

    async def _get_user(
        self,
        user_id: int,
    ) -> User:
        result = await self.db.execute(
            select(User).where(
                User.id == user_id
            )
        )

        user = result.scalar_one_or_none()

        if user is None:
            raise TransactionServiceError(
                "Utilisateur introuvable."
            )

        return user

    # ==========================================================
    # CREATE TRANSACTION
    # ==========================================================

    async def create_transaction(
        self,
        buyer: User,
        listing_id: int,
    ) -> Transaction:

        listing = await self._get_listing(listing_id)

        if listing.seller_id == buyer.id:
            raise TransactionServiceError(
                "Vous ne pouvez pas acheter votre propre annonce."
            )

        if listing.status != "published":
            raise TransactionServiceError(
                "Cette annonce n'est plus disponible."
            )

        if not listing.is_public:
            raise TransactionServiceError(
                "Cette annonce n'est pas publique."
            )

        if listing.price is None:
            raise TransactionServiceError(
                "Le prix de cette annonce est invalide."
            )

        price = self._money(listing.price)

        if price <= Decimal("0.00"):
            raise TransactionServiceError(
                "Le prix doit être supérieur à zéro."
            )

        fee_rate = self._money(
            listing.platform_fee_rate
        )

        platform_fee = self._money(
            price * fee_rate
        )

        seller_amount = self._money(
            price - platform_fee
        )

        if seller_amount < Decimal("0.00"):
            raise TransactionServiceError(
                "Le montant vendeur est invalide."
            )

        transaction = Transaction(
            reference=self._reference("NMX-TX"),
            listing_id=listing.id,
            buyer_id=buyer.id,
            seller_id=listing.seller_id,
            channel_price=price,
            platform_fee=platform_fee,
            provider_fee=Decimal("0.00"),
            total_buyer_amount=price,
            seller_amount=seller_amount,
            currency=listing.currency,
            platform_fee_rate=fee_rate,
            status="pending_payment",
            payment_provider=None,
            payment_reference=None,
            jessikapay_request_id=None,
            payment_status="pending",
            escrow_held=False,
        )

        listing.status = "reserved"

        self.db.add(transaction)

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            await self.notifications.transaction_created(
                transaction=transaction,
                buyer=buyer,
            )
        except Exception:
            # Une notification Telegram ne doit jamais
            # annuler une transaction déjà créée.
            pass

        return transaction

    # ==========================================================
    # CREATE PAYMENT
    # ==========================================================

    async def create_payment(
        self,
        transaction_id: int,
    ) -> dict:

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "pending_payment":
            raise TransactionServiceError(
                "Cette transaction n'attend pas un paiement."
            )

        if transaction.payment_status == "completed":
            raise TransactionServiceError(
                "Le paiement de cette transaction est déjà confirmé."
            )

        if transaction.currency != "XAF":
            raise TransactionServiceError(
                "Le paiement JessiKaPay de cette transaction "
                "est actuellement limité au XAF."
            )

        if not settings.NEXA_JP_NUMBER:
            raise TransactionServiceError(
                "Le compte JessiKaPay de NEXA n'est pas configuré."
            )

        amount = int(
            self._money(
                transaction.total_buyer_amount
            )
        )

        if amount <= 0:
            raise TransactionServiceError(
                "Le montant du paiement est invalide."
            )

        payment_reference = (
            f"NMX-PAY-{transaction.reference}"
        )

        try:
            response = (
                await self.jessikapay.create_payment_request(
                    jp_number=settings.NEXA_JP_NUMBER,
                    amount=amount,
                    reference=payment_reference,
                    description=(
                        f"NexMarket - transaction "
                        f"{transaction.reference}"
                    ),
                )
            )

        except JessiKaPayError as exc:
            raise TransactionServiceError(
                f"JessiKaPay a refusé la demande de paiement : {exc}"
            ) from exc

        request_id = response.get("request_id")

        if not request_id:
            raise TransactionServiceError(
                "JessiKaPay n'a pas retourné de request_id."
            )

        transaction.payment_provider = "jessikapay"
        transaction.payment_reference = payment_reference
        transaction.jessikapay_request_id = str(
            request_id
        )
        transaction.payment_status = str(
            response.get("status", "pending")
        ).lower()

        await self.db.commit()
        await self.db.refresh(transaction)

        return {
            "transaction_id": transaction.id,
            "reference": transaction.reference,
            "request_id": transaction.jessikapay_request_id,
            "payment_reference": transaction.payment_reference,
            "payment_link": response.get(
                "payment_link"
            ),
            "code": response.get("code"),
            "amount": amount,
            "currency": transaction.currency,
            "status": transaction.payment_status,
            "expires_at": response.get("expires_at"),
        }

    # ==========================================================
    # CONFIRM PAYMENT
    # ==========================================================

    async def confirm_payment(
        self,
        transaction_id: int,
        provider_status: dict,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status not in {
            "pending_payment",
            "payment_confirmed",
            "waiting_admin",
        }:
            raise TransactionServiceError(
                "Cette transaction ne peut plus être confirmée comme payée."
            )

        provider_state = str(
            provider_status.get("status", "")
        ).lower()

        if provider_state not in {
            "completed",
            "paid",
        }:
            raise TransactionServiceError(
                "JessiKaPay ne confirme pas encore ce paiement."
            )

        # Idempotence : si déjà confirmé, on retourne
        # simplement la transaction.
        if transaction.escrow_held:
            return transaction

        transaction.payment_status = "completed"
        transaction.status = "waiting_admin"
        transaction.payment_confirmed_at = (
            datetime.now(timezone.utc)
        )

        # Important :
        # le paiement est reçu sur le compte NEXA/JessiKaPay.
        # On marque donc l'escrow interne comme détenu.
        transaction.escrow_held = True
        transaction.escrow_held_at = (
            datetime.now(timezone.utc)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            buyer = await self._get_user(
                transaction.buyer_id
            )

            await self.notifications.payment_confirmed(
                transaction=transaction,
                buyer=buyer,
            )
        except Exception:
            pass

        return transaction

    # ==========================================================
    # ASSIGN ADMIN
    # ==========================================================

    async def assign_admin(
        self,
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

        if transaction.status not in {
            "waiting_admin",
            "payment_confirmed",
        }:
            raise TransactionServiceError(
                "Cette transaction ne peut pas être assignée."
            )

        transaction.assigned_admin_id = admin.id

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            buyer = await self._get_user(
                transaction.buyer_id
            )
            seller = await self._get_user(
                transaction.seller_id
            )

            await self.notifications.admin_assigned(
                transaction=transaction,
                buyer=buyer,
                seller=seller,
                admin=admin,
            )
        except Exception:
            pass

        return transaction

    # ==========================================================
    # START TRANSFER
    # ==========================================================

    async def start_transfer(
        self,
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

        if transaction.status not in {
            "waiting_admin",
            "payment_confirmed",
        }:
            raise TransactionServiceError(
                "Le transfert ne peut pas commencer dans cet état."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "Les fonds ne sont pas sécurisés."
            )

        transaction.assigned_admin_id = admin.id
        transaction.status = "transfer_in_progress"
        transaction.transfer_started_at = (
            datetime.now(timezone.utc)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            buyer = await self._get_user(
                transaction.buyer_id
            )
            seller = await self._get_user(
                transaction.seller_id
            )

            await self.notifications.transfer_started(
                transaction=transaction,
                buyer=buyer,
                seller=seller,
            )
        except Exception:
            pass

        return transaction

    # ==========================================================
    # COMPLETE TRANSFER
    # ==========================================================

    async def complete_transfer(
        self,
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

        if transaction.status != "transfer_in_progress":
            raise TransactionServiceError(
                "Le transfert n'est pas actuellement en cours."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "Les fonds ne sont pas sécurisés."
            )

        now = datetime.now(timezone.utc)

        transaction.assigned_admin_id = admin.id
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

        try:
            buyer = await self._get_user(
                transaction.buyer_id
            )
            seller = await self._get_user(
                transaction.seller_id
            )

            await self.notifications.protection_started(
                transaction=transaction,
                buyer=buyer,
                seller=seller,
            )
        except Exception:
            pass

        return transaction

    # ==========================================================
    # FINISH PROTECTION
    # ==========================================================

    async def finish_protection(
        self,
        transaction_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "protection_period":
            raise TransactionServiceError(
                "Cette transaction n'est pas en période de protection."
            )

        if not transaction.protection_ends_at:
            raise TransactionServiceError(
                "La date de fin de protection est absente."
            )

        now = datetime.now(timezone.utc)

        protection_ends = (
            transaction.protection_ends_at
        )

        if protection_ends.tzinfo is None:
            protection_ends = protection_ends.replace(
                tzinfo=timezone.utc
            )

        if now < protection_ends:
            raise TransactionServiceError(
                "La période de protection n'est pas encore terminée."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "Aucun montant n'est actuellement détenu en escrow."
            )

        transaction.status = "completed"

        if transaction.buyer_confirmed_at is None:
            transaction.buyer_confirmed_at = now

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            buyer = await self._get_user(
                transaction.buyer_id
            )
            seller = await self._get_user(
                transaction.seller_id
            )

            await self.notifications.transaction_completed(
                transaction=transaction,
                buyer=buyer,
                seller=seller,
            )
        except Exception:
            pass

        return transaction

    # ==========================================================
    # SELLER PAYOUT
    # ==========================================================

    async def payout_seller(
        self,
        transaction_id: int,
        seller_jp_number: str,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "completed":
            raise TransactionServiceError(
                "Le vendeur ne peut être payé qu'après "
                "la fin de la transaction."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "L'escrow n'est pas actif."
            )

        if transaction.seller_paid_at is not None:
            return transaction

        if transaction.currency != "XAF":
            raise TransactionServiceError(
                "Le payout JessiKaPay est actuellement "
                "limité au XAF."
            )

        if not seller_jp_number.strip():
            raise TransactionServiceError(
                "Le numéro JessiKaPay du vendeur est obligatoire."
            )

        amount = int(
            self._money(
                transaction.seller_amount
            )
        )

        if amount <= 0:
            raise TransactionServiceError(
                "Le montant à payer au vendeur est invalide."
            )

        payout_reference = (
            f"NMX-PAYOUT-{transaction.reference}"
        )

        try:
            response = await self.jessikapay.create_payout(
                jp_number=seller_jp_number.strip(),
                amount=amount,
                reference=payout_reference,
                description=(
                    f"NexMarket - paiement vendeur "
                    f"{transaction.reference}"
                ),
            )

        except JessiKaPayError as exc:
            raise TransactionServiceError(
                f"JessiKaPay a refusé le payout : {exc}"
            ) from exc

        payout_transaction_id = response.get(
            "transaction_id"
        )

        if not payout_transaction_id:
            raise TransactionServiceError(
                "JessiKaPay n'a pas retourné de transaction_id."
            )

        # Le payout JessiKaPay est accepté.
        #
        # IMPORTANT :
        # on enregistre la référence mais on ne prétend pas
        # encore que le vendeur a reçu l'argent.
        transaction.seller_payout_reference = (
            payout_reference
        )

        transaction.jessikapay_payout_transaction_id = (
            str(payout_transaction_id)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ==========================================================
    # CONFIRM SELLER PAYOUT
    # ==========================================================

    async def confirm_seller_payout(
        self,
        transaction_id: int,
        provider_transaction_id: str,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id
        )

        if transaction.status != "completed":
            raise TransactionServiceError(
                "La transaction n'est pas terminée."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "L'escrow n'est pas actif."
            )

        expected_id = (
            transaction.jessikapay_payout_transaction_id
        )

        if expected_id and str(expected_id) != str(
            provider_transaction_id
        ):
            raise TransactionServiceError(
                "La référence du payout ne correspond pas."
            )

        if transaction.seller_paid_at is not None:
            return transaction

        now = datetime.now(timezone.utc)

        transaction.seller_paid_at = now

        # Le paiement du vendeur étant confirmé,
        # l'escrow NexMarket peut être considéré comme libéré.
        transaction.escrow_held = False

        transaction.nexmarket_fee_recorded_at = now

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            seller = await self._get_user(
                transaction.seller_id
            )

            await self.notifications.seller_paid(
                transaction=transaction,
                seller=seller,
            )
        except Exception:
            pass

        return transaction

    # ==========================================================
    # CANCEL TRANSACTION
    # ==========================================================

    async def cancel_transaction(
        self,
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
            "cancelled",
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
            transaction.admin_notes = reason.strip()

        # Le montant n'est plus considéré comme détenu
        # si la transaction est annulée avant le paiement.
        if transaction.payment_status != "completed":
            transaction.escrow_held = False

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ==========================================================
    # OPEN DISPUTE
    # ==========================================================

    async def open_dispute(
        self,
        transaction_id: int,
        user: User,
        reason: str,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id
        )

        if (
            transaction.buyer_id != user.id
            and transaction.seller_id != user.id
            and not user.is_admin
        ):
            raise TransactionServiceError(
                "Vous ne participez pas à cette transaction."
            )

        if transaction.status in {
            "cancelled",
            "refunded",
        }:
            raise TransactionServiceError(
                "Cette transaction ne peut plus recevoir de litige."
            )

        if transaction.status == "disputed":
            raise TransactionServiceError(
                "Un litige est déjà ouvert."
            )

        cleaned_reason = reason.strip()

        if not cleaned_reason:
            raise TransactionServiceError(
                "Le motif du litige est obligatoire."
            )

        transaction.status = "disputed"
        transaction.dispute_reason = cleaned_reason
        transaction.disputed_at = (
            datetime.now(timezone.utc)
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        try:
            buyer = await self._get_user(
                transaction.buyer_id
            )
            seller = await self._get_user(
                transaction.seller_id
            )

            await self.notifications.dispute_opened(
                transaction=transaction,
                buyer=buyer,
                seller=seller,
            )
        except Exception:
            pass

        return transaction
