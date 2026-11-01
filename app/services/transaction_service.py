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
from app.services.notification_service import notify_user_id
from app.services.wallet_service import (
    DuplicateOperationError,
    WalletService,
)


class TransactionServiceError(Exception):
    """Erreur métier liée aux transactions."""


class TransactionService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet = WalletService(db)

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

        # Le taux est stocké avec 6 décimales : pas d'arrondi à 0.01.
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

        await self._notify(
            transaction,
            buyer="🔄 Le transfert du canal a commencé.",
            seller="🔄 Le transfert du canal a commencé.",
        )

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

        await self._notify(
            transaction,
            buyer="🛡️ Transfert terminé. Vérifiez le canal : vous pouvez confirmer la réception ou ouvrir un litige pendant la période de protection.",
            seller="🛡️ Transfert terminé. Vos fonds seront versés à la fin de la période de protection.",
        )

        return transaction

    # ============================================================
    # NOTIFICATIONS TELEGRAM (acheteur / vendeur)
    # ============================================================

    async def _notify(
        self,
        transaction: Transaction,
        *,
        buyer: str | None = None,
        seller: str | None = None,
    ) -> None:
        ref = transaction.reference

        if buyer:
            await notify_user_id(
                self.db, transaction.buyer_id, f"{buyer}\n\nRéférence : {ref}"
            )

        if seller:
            await notify_user_id(
                self.db, transaction.seller_id, f"{seller}\n\nRéférence : {ref}"
            )

    # ============================================================
    # PAIEMENT PAR WALLET (escrow)
    # ============================================================
    #
    # Modèle : l'acheteur recharge son wallet (dépôt JessiKaPay), puis
    # le prix est BLOQUÉ dans son wallet à l'achat. Il n'est versé au
    # wallet du vendeur (moins la commission) qu'à la fin de la
    # période de protection, ou remboursé en cas de litige.
    # JessiKaPay ne sert qu'aux dépôts et aux retraits.

    async def pay_with_wallet(
        self,
        *,
        transaction_id: int,
        buyer_id: int,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.buyer_id != buyer_id:
            raise TransactionServiceError(
                "Seul l'acheteur peut payer cette transaction."
            )

        # Idempotence
        if transaction.payment_status == "completed":
            return transaction

        if transaction.status != "pending_payment":
            raise TransactionServiceError(
                "Cette transaction n'attend plus de paiement."
            )

        amount = self._money(transaction.total_buyer_amount)
        currency = transaction.currency.upper()

        buyer_wallet = await self.wallet.get_wallet(buyer_id)
        seller_wallet = await self.wallet.get_wallet(
            transaction.seller_id
        )

        if (
            buyer_wallet.currency.upper() != currency
            or seller_wallet.currency.upper() != currency
        ):
            raise TransactionServiceError(
                "La devise de l'annonce ne correspond pas à celle "
                "des portefeuilles."
            )

        # Lève WalletServiceError("Solde insuffisant...") si besoin.
        try:
            await self.wallet.block(
                user_id=buyer_id,
                amount=amount,
                reference=f"{transaction.reference}-HOLD",
                description=(
                    f"Fonds réservés pour {transaction.reference}"
                ),
            )
        except DuplicateOperationError:
            pass  # déjà bloqué lors d'un essai interrompu

        now = self._now()

        transaction.payment_provider = "wallet"
        transaction.payment_status = "completed"
        transaction.payment_confirmed_at = now
        transaction.escrow_held = True
        transaction.escrow_held_at = now
        transaction.status = "waiting_admin"

        await self.db.commit()
        await self.db.refresh(transaction)

        await self._notify(
            transaction,
            buyer="🛒 Achat confirmé : les fonds sont réservés. Un administrateur va organiser le transfert du canal.",
            seller="💰 Nouvelle vente ! Les fonds de l'acheteur sont sécurisés. Un administrateur va vous contacter pour le transfert du canal.",
        )

        return transaction

    async def purchase(
        self,
        *,
        buyer_id: int,
        listing_id: int,
    ) -> Transaction:
        """Création de la transaction + blocage des fonds, en un geste."""

        transaction = await self.create_transaction(
            buyer_id=buyer_id,
            listing_id=listing_id,
        )

        try:
            return await self.pay_with_wallet(
                transaction_id=transaction.id,
                buyer_id=buyer_id,
            )
        except Exception:
            await self.db.rollback()

            # Solde insuffisant, etc. : rien n'est bloqué, on annule
            # et on remet l'annonce en vente.
            try:
                await self.cancel_transaction(
                    transaction_id=transaction.id,
                    user_id=buyer_id,
                    notify=False,
                )
            except Exception:
                await self.db.rollback()

            raise

    # ============================================================
    # RÈGLEMENT / REMBOURSEMENT
    # ============================================================

    async def _settle_to_seller(
        self,
        transaction: Transaction,
    ) -> None:
        """
        Consomme les fonds bloqués de l'acheteur, crédite le vendeur
        (prix - commission) et enregistre la commission NexMarket.
        Chaque mouvement a une référence unique : rejouable sans risque.
        """

        total = self._money(transaction.total_buyer_amount)
        seller_amount = self._money(transaction.seller_amount)

        try:
            await self.wallet.consume_blocked(
                user_id=transaction.buyer_id,
                amount=total,
                reference=f"{transaction.reference}-CONSUME",
                description=(
                    f"Paiement de {transaction.reference}"
                ),
            )
        except DuplicateOperationError:
            pass

        try:
            await self.wallet.credit(
                user_id=transaction.seller_id,
                amount=seller_amount,
                reference=f"{transaction.reference}-SELLER",
                operation_type="sale",
                description=(
                    f"Vente {transaction.reference}"
                ),
            )
        except DuplicateOperationError:
            pass

        await self._record_platform_fee(transaction)

        transaction.seller_paid_at = self._now()
        transaction.escrow_held = False

    async def _refund_escrow(
        self,
        transaction: Transaction,
    ) -> None:
        """Rend les fonds bloqués à l'acheteur."""

        reference = f"{transaction.reference}-REFUND"

        try:
            await self.wallet.release_blocked(
                user_id=transaction.buyer_id,
                amount=self._money(transaction.total_buyer_amount),
                reference=reference,
                description=(
                    f"Remboursement de {transaction.reference}"
                ),
            )
        except DuplicateOperationError:
            pass

        transaction.escrow_held = False
        transaction.refunded_at = self._now()
        transaction.refund_reference = reference

    async def _complete(
        self,
        transaction: Transaction,
    ) -> None:
        await self._settle_to_seller(transaction)

        transaction.status = "completed"
        transaction.completed_at = self._now()

        # La chaîne est vendue : l'annonce sort de la marketplace.
        listing = await self._get_listing(
            transaction.listing_id,
            lock=True,
        )
        listing.status = "sold"
        listing.is_public = False

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

        await self._complete(transaction)

        await self.db.commit()
        await self.db.refresh(transaction)

        await self._notify(
            transaction,
            buyer="✅ Transaction terminée. Merci d'utiliser NexMarket !",
            seller="✅ Vente terminée : le montant (moins la commission) a été crédité sur votre portefeuille.",
        )

        return transaction

    async def confirm_receipt(
        self,
        *,
        transaction_id: int,
        user_id: int,
    ) -> Transaction:
        """L'acheteur confirme avoir reçu le canal : fonds libérés."""

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        if transaction.buyer_id != user_id:
            raise TransactionServiceError(
                "Seul l'acheteur peut confirmer la réception."
            )

        if transaction.status != "protection_period":
            raise TransactionServiceError(
                "Le canal n'a pas encore été transféré."
            )

        transaction.buyer_confirmed_at = self._now()

        await self._complete(transaction)

        await self.db.commit()
        await self.db.refresh(transaction)

        await self._notify(
            transaction,
            buyer="✅ Réception confirmée. Merci !",
            seller="✅ L'acheteur a confirmé la réception : le montant a été crédité sur votre portefeuille.",
        )

        return transaction

    async def auto_finish_protections(self) -> int:
        """
        Clôture les transactions dont la protection est terminée sans
        litige (appelée périodiquement par l'application).
        """

        result = await self.db.execute(
            select(Transaction.id).where(
                Transaction.status == "protection_period",
                Transaction.protection_ends_at <= self._now(),
            ).limit(50)
        )

        done = 0

        for (transaction_id,) in result.all():
            try:
                await self.finish_protection(transaction_id)
                done += 1
            except Exception:
                await self.db.rollback()

        return done

    # ============================================================
    # RÉSOLUTION ADMIN (litige / remboursement)
    # ============================================================

    async def resolve(
        self,
        *,
        transaction_id: int,
        action: str,
        admin_id: int,
        note: str | None = None,
    ) -> Transaction:

        transaction = await self._get_transaction(
            transaction_id,
            lock=True,
        )

        admin = await self._get_user(admin_id)

        if not admin.is_admin:
            raise TransactionServiceError("Accès administrateur requis.")

        if action == "refund_buyer":
            allowed = (
                "waiting_admin",
                "transfer_started",
                "protection_period",
                "disputed",
            )
        elif action == "release_seller":
            allowed = ("protection_period", "disputed")
        else:
            raise TransactionServiceError("Action inconnue.")

        if transaction.status not in allowed:
            raise TransactionServiceError(
                "Cette action n'est pas possible dans l'état "
                f"« {transaction.status} »."
            )

        if not transaction.escrow_held:
            raise TransactionServiceError(
                "Les fonds de cette transaction ne sont plus "
                "bloqués."
            )

        if action == "refund_buyer":
            await self._refund_escrow(transaction)
            transaction.status = "refunded"

            listing = await self._get_listing(
                transaction.listing_id,
                lock=True,
            )
            if listing.status == "reserved":
                listing.status = "published"
        else:
            await self._complete(transaction)

        transaction.dispute_resolved_at = self._now()
        transaction.assigned_admin_id = (
            transaction.assigned_admin_id or admin.id
        )

        if note:
            transaction.admin_note = (
                ((transaction.admin_note or "") + "\n" + note).strip()
            )

        await self.db.commit()
        await self.db.refresh(transaction)

        if transaction.status == "refunded":
            await self._notify(
                transaction,
                buyer="↩️ Litige résolu : vous avez été remboursé.",
                seller="↩️ Litige résolu en faveur de l'acheteur : la transaction est remboursée.",
            )
        else:
            await self._notify(
                transaction,
                buyer="✅ Litige résolu : la transaction est conclue.",
                seller="✅ Litige résolu en votre faveur : le montant a été crédité sur votre portefeuille.",
            )

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
                f"Commission NexMarket de "
                f"{Decimal(str(transaction.platform_fee_rate)) * 100:.2f} % "
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

        if transaction.status not in (
            "waiting_admin",
            "transfer_started",
            "protection_period",
        ):
            raise TransactionServiceError(
                "Un litige ne peut être ouvert que sur une transaction "
                "payée et pas encore clôturée."
            )

        if transaction.seller_paid_at:
            raise TransactionServiceError(
                "Le vendeur a déjà été payé : litige impossible."
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

        await self._notify(
            transaction,
            buyer="⚠️ Un litige a été ouvert. Un administrateur va examiner la situation.",
            seller="⚠️ Un litige a été ouvert. Un administrateur va examiner la situation.",
        )

        return transaction

    # ============================================================
    # CANCEL TRANSACTION
    # ============================================================

    async def cancel_transaction(
        self,
        *,
        transaction_id: int,
        user_id: int,
        notify: bool = True,
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

        # Avant le début du transfert, rien n'a été livré : on peut
        # annuler et rembourser. Ensuite il faut passer par un litige.
        if transaction.status not in (
            "pending_payment",
            "waiting_admin",
        ):
            raise TransactionServiceError(
                "Cette transaction ne peut plus être annulée. "
                "Ouvrez un litige pour être remboursé."
            )

        if transaction.escrow_held:
            await self._refund_escrow(transaction)

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

        if notify:
            await self._notify(
                transaction,
                buyer="❌ Transaction annulée." + (" Vos fonds ont été libérés." if transaction.refunded_at else ""),
                seller="❌ La transaction a été annulée ; votre annonce est de nouveau en vente.",
            )

        return transaction

    # ============================================================
    # EXPIRATION DES RÉSERVATIONS NON PAYÉES
    # ============================================================

    async def expire_unpaid(self, ttl_minutes: int) -> int:
        """
        Annule les transactions jamais payées et libère l'annonce
        (sinon un utilisateur pourrait bloquer une annonce à vie).
        """

        limit = self._now() - timedelta(minutes=ttl_minutes)

        result = await self.db.execute(
            select(Transaction)
            .where(
                Transaction.status == "pending_payment",
                Transaction.payment_status != "completed",
                Transaction.created_at < limit,
            )
            .with_for_update(skip_locked=True)
        )

        count = 0

        for transaction in result.scalars().all():
            transaction.status = "cancelled"
            transaction.cancelled_at = self._now()
            transaction.cancellation_reason = (
                "Expirée : paiement non reçu à temps."
            )

            listing = await self._get_listing(
                transaction.listing_id,
                lock=True,
            )

            if listing.status == "reserved":
                listing.status = "published"

            count += 1

        await self.db.commit()

        return count
