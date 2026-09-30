from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.listing import Listing
from app.models.platform import PlatformLedger, PlatformWallet
from app.models.transaction import Transaction
from app.models.user import User
from app.services.jessikapay_service import (
    JessiKaPayError,
    JessiKaPayService,
)


class TransactionServiceError(Exception):
    """Erreur métier liée aux transactions."""


class TransactionService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.jessikapay = JessiKaPayService()

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _money(value) -> Decimal:
        return Decimal(str(value)).quantize(
            Decimal("0.01")
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _reference() -> str:
        return f"NMX-TX-{uuid4().hex[:16].upper()}"

    async def _get_transaction(
        self,
        transaction_id: int,
        lock: bool = False,
    ) -> Transaction:

        query = select(Transaction).where(
            Transaction.id == transaction_id
        )

        if lock:
            query = query.with_for_update()

        result = await self.db.execute(query)

        transaction = result.scalar_one_or_none()

        if not transaction:
            raise TransactionServiceError(
                "Transaction introuvable."
            )

        return transaction

    async def _get_listing(
        self,
        listing_id: int,
        lock: bool = False,
    ) -> Listing:

        query = select(Listing).where(
            Listing.id == listing_id
        )

        if lock:
            query = query.with_for_update()

        result = await self.db.execute(query)

        listing = result.scalar_one_or_none()

        if not listing:
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

        if not user:
            raise TransactionServiceError(
                "Utilisateur introuvable."
            )

        if not user.is_active:
            raise TransactionServiceError(
                "Le compte utilisateur est désactivé."
            )

        return user

    # ============================================================
    # CREATE TRANSACTION
    # ============================================================

    async def create_transaction(
        self,
        *,
        buyer_id: int,
        listing_id: int,
    ) -> Transaction:

        buyer = await self._get_user(buyer_id)

        listing = await self._get_listing(
            listing_id,
            lock=True,
        )

        if not listing.is_public:
            raise TransactionServiceError(
                "Cette annonce n'est pas disponible."
            )

        if listing.status != "published":
            raise TransactionServiceError(
                "Cette annonce n'est plus disponible."
            )

        if listing.seller_id == buyer.id:
            raise TransactionServiceError(
                "Vous ne pouvez pas acheter votre propre annonce."
            )

        price = self._money(listing.price)

        if price <= 0:
            raise TransactionServiceError(
                "Le prix de l'annonce est invalide."
            )

        currency = listing.currency.upper()

        fee_rate = self._money(
            listing.platform_fee_rate
        )

        # Le taux est stocké avec davantage de précision
        # dans la base. On récupère donc sa valeur originale.
        fee_rate = Decimal(
            str(listing.platform_fee_rate)
        )

        platform_fee = self._money(
            price * fee_rate
        )

        seller_amount = self._money(
            price - platform_fee
        )

        if seller_amount < 0:
            raise TransactionServiceError(
                "Le montant vendeur est invalide."
            )

        transaction = Transaction(
            reference=self._reference(),
            listing_id=listing.id,
            buyer_id=buyer.id,
            seller_id=listing.seller_id,
            channel_price=price,
            platform_fee=platform_fee,
            provider_fee=Decimal("0.00"),
            total_buyer_amount=price,
            seller_amount=seller_amount,
            currency=currency,
            platform_fee_rate=fee_rate,
            status="pending_payment",
            escrow_held=False,
        )

        self.db.add(transaction)

        # Réserver l'annonce immédiatement.
        listing.status = "reserved"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # CREATE PAYMENT
    # ============================================================

    async def create_payment(
        self,
        transaction_id: int,
    ) -> dict:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.status != "pending_payment":
            raise TransactionServiceError(
                "Cette transaction n'attend pas un paiement."
            )

        if transaction.currency.upper() != "XAF":
            raise TransactionServiceError(
                "Les paiements JessiKaPay sont actuellement "
                "traités uniquement en XAF."
            )

        if not settings.NEXA_JP_NUMBER:
            raise TransactionServiceError(
                "Le compte JessiKaPay de NEXA n'est pas configuré."
            )

        amount = self._money(
            transaction.total_buyer_amount
        )

        if amount <= 0:
            raise TransactionServiceError(
                "Montant de paiement invalide."
            )

        reference = (
            f"NMX-PAY-{transaction.reference}"
        )

        try:
            response = (
                await self.jessikapay.create_payment_request(
                    jp_number=settings.NEXA_JP_NUMBER,
                    amount=int(amount),
                    reference=reference,
                    description=(
                        f"Paiement NexMarket "
                        f"{transaction.reference}"
                    ),
                )
            )

        except JessiKaPayError as exc:
            raise TransactionServiceError(
                f"Impossible de créer le paiement : {exc}"
            ) from exc

        request_id = response.get(
            "request_id"
        )

        if not request_id:
            raise TransactionServiceError(
                "JessiKaPay n'a pas retourné de request_id."
            )

        transaction.payment_provider = "jessikapay"
        transaction.payment_reference = reference
        transaction.jessikapay_request_id = str(
            request_id
        )
        transaction.payment_status = response.get(
            "status",
            "pending",
        )

        await self.db.commit()

        return {
            "transaction_id": transaction.id,
            "reference": transaction.reference,
            "request_id": request_id,
            "code": response.get("code"),
            "payment_link": response.get(
                "payment_link"
            ),
            "amount": amount,
            "status": response.get(
                "status",
                "pending",
            ),
            "expires_at": response.get(
                "expires_at"
            ),
        }

    # ============================================================
    # CONFIRM PAYMENT
    # ============================================================

    async def confirm_payment(
        self,
        *,
        payment_reference: str | None = None,
        request_id: str | None = None,
        amount: Decimal,
    ) -> Transaction:

        query = select(Transaction)

        if request_id:
            query = query.where(
                Transaction.jessikapay_request_id
                == str(request_id)
            )

        elif payment_reference:
            query = query.where(
                Transaction.payment_reference
                == payment_reference
            )

        else:
            raise TransactionServiceError(
                "Référence de paiement manquante."
            )

        query = query.with_for_update()

        result = await self.db.execute(query)

        transaction = result.scalar_one_or_none()

        if not transaction:
            raise TransactionServiceError(
                "Transaction correspondant au paiement introuvable."
            )

        # Idempotence
        if transaction.payment_status == "completed":
            return transaction

        expected_amount = self._money(
            transaction.total_buyer_amount
        )

        received_amount = self._money(
            amount
        )

        if expected_amount != received_amount:
            raise TransactionServiceError(
                "Le montant reçu ne correspond pas "
                "au montant de la transaction."
            )

        transaction.payment_status = "completed"
        transaction.payment_confirmed_at = (
            self._now()
        )

        transaction.escrow_held = True
        transaction.escrow_held_at = (
            self._now()
        )

        transaction.status = "waiting_admin"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # ASSIGN ADMIN
    # ============================================================

    async def assign_admin(
        self,
        *,
        transaction_id: int,
        admin_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        admin = await self._get_user(admin_id)

        if not admin.is_admin:
            raise TransactionServiceError(
                "L'utilisateur sélectionné n'est pas administrateur."
            )

        transaction.assigned_admin_id = admin.id

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # START CHANNEL TRANSFER
    # ============================================================

    async def start_transfer(
        self,
        transaction_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.status != "waiting_admin":
            raise TransactionServiceError(
                "La transaction n'est pas prête pour le transfert."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "Les fonds ne sont pas protégés."
            )

        transaction.status = "transfer_started"
        transaction.transfer_started_at = (
            self._now()
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # COMPLETE CHANNEL TRANSFER
    # ============================================================

    async def complete_transfer(
        self,
        transaction_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.status != "transfer_started":
            raise TransactionServiceError(
                "Le transfert n'est pas en cours."
            )

        now = self._now()

        transaction.transfer_completed_at = now

        transaction.protection_ends_at = (
            now
            + timedelta(
                minutes=settings.ESCROW_PROTECTION_MINUTES
            )
        )

        transaction.status = "protection_period"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # FINISH PROTECTION
    # ============================================================

    async def finish_protection(
        self,
        transaction_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.status != "protection_period":
            raise TransactionServiceError(
                "La transaction n'est pas en période de protection."
            )

        if not transaction.protection_ends_at:
            raise TransactionServiceError(
                "La date de fin de protection est manquante."
            )

        if self._now() < transaction.protection_ends_at:
            raise TransactionServiceError(
                "La période de protection n'est pas terminée."
            )

        transaction.status = "completed"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # PAY SELLER
    # ============================================================

    async def payout_seller(
        self,
        *,
        transaction_id: int,
        seller_jp_number: str,
    ) -> dict:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.status != "completed":
            raise TransactionServiceError(
                "La transaction n'est pas terminée."
            )

        if transaction.seller_paid_at:
            raise TransactionServiceError(
                "Le vendeur a déjà été payé."
            )

        if transaction.currency.upper() != "XAF":
            raise TransactionServiceError(
                "Les payouts JessiKaPay sont actuellement "
                "traités uniquement en XAF."
            )

        if not seller_jp_number.strip():
            raise TransactionServiceError(
                "Le numéro JessiKaPay du vendeur est obligatoire."
            )

        amount = self._money(
            transaction.seller_amount
        )

        if amount <= 0:
            raise TransactionServiceError(
                "Montant vendeur invalide."
            )

        payout_reference = (
            f"NMX-PAYOUT-{transaction.reference}"
        )

        # Ne pas lancer deux payouts pour la même transaction.
        if transaction.jessikapay_payout_transaction_id:
            raise TransactionServiceError(
                "Un payout JessiKaPay existe déjà pour cette transaction."
            )

        try:
            response = await self.jessikapay.create_payout(
                jp_number=seller_jp_number.strip(),
                amount=int(amount),
                reference=payout_reference,
                description=(
                    f"Paiement vendeur NexMarket "
                    f"{transaction.reference}"
                ),
            )

        except JessiKaPayError as exc:
            raise TransactionServiceError(
                f"Impossible d'effectuer le payout : {exc}"
            ) from exc

        provider_transaction_id = response.get(
            "transaction_id"
        )

        if not provider_transaction_id:
            raise TransactionServiceError(
                "JessiKaPay n'a pas retourné de transaction_id."
            )

        transaction.seller_payout_reference = (
            payout_reference
        )

        transaction.jessikapay_payout_transaction_id = (
            str(provider_transaction_id)
        )

        # IMPORTANT :
        # seller_paid_at reste NULL.
        #
        # Le paiement est définitif uniquement après
        # credit.completed.

        await self.db.commit()
        await self.db.refresh(transaction)

        return {
            "transaction_id": transaction.id,
            "reference": transaction.reference,
            "payout_reference": payout_reference,
            "provider_transaction_id": (
                provider_transaction_id
            ),
            "amount": amount,
            "status": "payout_sent",
        }

    # ============================================================
    # CONFIRM SELLER PAYOUT
    # ============================================================

    async def confirm_seller_payout(
        self,
        *,
        provider_transaction_id: str,
        amount: Decimal,
        reference: str | None = None,
    ) -> Transaction:

        result = await self.db.execute(
            select(Transaction)
            .where(
                Transaction.jessikapay_payout_transaction_id
                == str(provider_transaction_id)
            )
            .with_for_update()
        )

        transaction = result.scalar_one_or_none()

        if not transaction:
            raise TransactionServiceError(
                "Transaction vendeur introuvable."
            )

        # Idempotence
        if transaction.seller_paid_at:
            return transaction

        expected_amount = self._money(
            transaction.seller_amount
        )

        received_amount = self._money(
            amount
        )

        if expected_amount != received_amount:
            raise TransactionServiceError(
                "Le montant du payout ne correspond pas "
                "au montant vendeur."
            )

        if reference:
            expected_reference = (
                f"NMX-PAYOUT-{transaction.reference}"
            )

            if reference != expected_reference:
                raise TransactionServiceError(
                    "La référence du payout est incorrecte."
                )

        transaction.seller_paid_at = self._now()

        transaction.escrow_held = False

        # --------------------------------------------------------
        # ENREGISTRER LA COMMISSION NEXMARKET
        # --------------------------------------------------------

        await self._record_platform_fee(
            transaction
        )

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # RECORD PLATFORM FEE
    # ============================================================

    async def _record_platform_fee(
        self,
        transaction: Transaction,
    ) -> None:

        # Idempotence supplémentaire.
        if transaction.nexmarket_fee_recorded_at:
            return

        fee = self._money(
            transaction.platform_fee
        )

        if fee <= 0:
            transaction.nexmarket_fee_recorded_at = (
                self._now()
            )
            return

        currency = transaction.currency.upper()

        # --------------------------------------------------------
        # LOCK / GET PLATFORM WALLET
        # --------------------------------------------------------

        result = await self.db.execute(
            select(PlatformWallet)
            .where(
                PlatformWallet.currency == currency
            )
            .with_for_update()
        )

        platform_wallet = (
            result.scalar_one_or_none()
        )

        # Création automatique si le wallet de la devise
        # n'existe pas encore.
        if not platform_wallet:

            platform_wallet = PlatformWallet(
                currency=currency,
                available_balance=Decimal("0.00"),
                blocked_balance=Decimal("0.00"),
                total_revenue=Decimal("0.00"),
                total_fees_collected=Decimal("0.00"),
            )

            self.db.add(platform_wallet)

            await self.db.flush()

        # --------------------------------------------------------
        # UNIQUE LEDGER REFERENCE
        # --------------------------------------------------------

        ledger_reference = (
            f"NMX-FEE-{transaction.reference}"
        )

        existing = await self.db.execute(
            select(PlatformLedger).where(
                PlatformLedger.reference
                == ledger_reference
            )
        )

        if existing.scalar_one_or_none():
            transaction.nexmarket_fee_recorded_at = (
                self._now()
            )
            return

        # --------------------------------------------------------
        # UPDATE PLATFORM WALLET
        # --------------------------------------------------------

        platform_wallet.available_balance = (
            self._money(
                platform_wallet.available_balance
            )
            + fee
        )

        platform_wallet.total_revenue = (
            self._money(
                platform_wallet.total_revenue
            )
            + fee
        )

        platform_wallet.total_fees_collected = (
            self._money(
                platform_wallet.total_fees_collected
            )
            + fee
        )

        # --------------------------------------------------------
        # CREATE LEDGER ENTRY
        # --------------------------------------------------------

        ledger = PlatformLedger(
            wallet_id=platform_wallet.id,
            transaction_id=transaction.id,
            reference=ledger_reference,
            operation_type="sale_commission",
            amount=fee,
            currency=currency,
            description=(
                f"Commission NexMarket de 5 % "
                f"sur la transaction {transaction.reference}"
            ),
        )

        self.db.add(ledger)

        transaction.nexmarket_fee_recorded_at = (
            self._now()
        )

    # ============================================================
    # OPEN DISPUTE
    # ============================================================

    async def open_dispute(
        self,
        *,
        transaction_id: int,
        user_id: int,
        reason: str,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if user_id not in (
            transaction.buyer_id,
            transaction.seller_id,
        ):
            raise TransactionServiceError(
                "Vous ne participez pas à cette transaction."
            )

        if transaction.status in (
            "cancelled",
            "refunded",
        ):
            raise TransactionServiceError(
                "Cette transaction est déjà clôturée."
            )

        if not reason.strip():
            raise TransactionServiceError(
                "La raison du litige est obligatoire."
            )

        transaction.status = "disputed"
        transaction.dispute_reason = reason.strip()
        transaction.disputed_at = self._now()

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    # ============================================================
    # CANCEL TRANSACTION
    # ============================================================

    async def cancel_transaction(
        self,
        *,
        transaction_id: int,
        user_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if user_id not in (
            transaction.buyer_id,
            transaction.seller_id,
        ):
            raise TransactionServiceError(
                "Accès refusé."
            )

        if transaction.status not in (
            "pending_payment",
            "waiting_admin",
        ):
            raise TransactionServiceError(
                "Cette transaction ne peut plus être annulée."
            )

        transaction.status = "cancelled"
        transaction.cancelled_at = self._now()

        # Libération de l'annonce.
        listing = await self._get_listing(
            transaction.listing_id,
            lock=True,
        )

        if listing.status == "reserved":
            listing.status = "published"

        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction
