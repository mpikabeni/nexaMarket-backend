from __future__ import annotations

import logging
import secrets
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.transaction import Transaction
from app.services.wallet_service import wallet_service


logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


class TransactionService:
    """
    Gestion des transactions NexMarket.

    Cycle principal :

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
    completed

    En cas de problème :

    cancelled / disputed / refunded
    """

    # =========================================================
    # REFERENCE
    # =========================================================

    @staticmethod
    def generate_reference() -> str:
        """
        Génère une référence unique côté application.
        """

        return (
            "NEX-"
            + secrets.token_hex(8).upper()
        )

    # =========================================================
    # CALCUL DES FRAIS
    # =========================================================

    @staticmethod
    def calculate_platform_fee(
        channel_price: Decimal,
    ) -> Decimal:
        """
        Calcule la commission NexMarket.

        Le taux vient de NEXMARKET_FEE_RATE.
        """

        rate = Decimal(
            str(settings.NEXMARKET_FEE_RATE or 0)
        )

        if rate < 0:
            rate = Decimal("0")

        fee = channel_price * rate

        return fee.quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )

    # =========================================================
    # CREER UNE TRANSACTION
    # =========================================================

    async def create_transaction(
        self,
        db: AsyncSession,
        listing_id: int,
        buyer_id: int,
        seller_id: int,
        channel_price: float,
        currency: str = "XAF",
    ) -> Transaction:

        price = money(channel_price)

        if price <= 0:
            raise ValueError(
                "Le prix de la transaction doit être supérieur à zéro."
            )

        if buyer_id == seller_id:
            raise ValueError(
                "Le vendeur ne peut pas acheter sa propre annonce."
            )

        # Vérifie qu'une transaction active n'existe pas déjà
        # pour cette annonce.
        result = await db.execute(
            select(Transaction)
            .where(
                Transaction.listing_id == listing_id,
                Transaction.buyer_id == buyer_id,
                Transaction.status.in_(
                    [
                        "pending_payment",
                        "payment_confirmed",
                        "waiting_admin",
                        "assigned",
                        "transfer_pending",
                        "disputed",
                    ]
                ),
            )
            .order_by(Transaction.created_at.desc())
        )

        existing = result.scalars().first()

        if existing:
            raise ValueError(
                "Une transaction active existe déjà "
                "pour cette annonce."
            )

        platform_fee = self.calculate_platform_fee(
            price
        )

        # Pour le moment le provider fee reste à 0.
        #
        # Il sera alimenté avec les frais réellement
        # retournés par Money Fusion lors du paiement.
        provider_fee = Decimal("0.00")

        total_buyer_amount = (
            price + provider_fee
        )

        seller_amount = (
            price - platform_fee
        )

        if seller_amount < 0:
            seller_amount = Decimal("0.00")

        transaction = Transaction(
            reference=self.generate_reference(),

            listing_id=listing_id,

            buyer_id=buyer_id,
            seller_id=seller_id,

            channel_price=price,

            platform_fee=platform_fee,
            provider_fee=provider_fee,

            total_buyer_amount=total_buyer_amount,
            seller_amount=seller_amount,

            currency=currency or settings.DEFAULT_CURRENCY,

            status="pending_payment",

            payment_provider="moneyfusion",
            payment_status="pending",
        )

        db.add(transaction)

        await db.flush()

        return transaction

    # =========================================================
    # RECUPERER UNE TRANSACTION
    # =========================================================

    async def get_transaction(
        self,
        db: AsyncSession,
        transaction_id: int,
        lock: bool = False,
    ) -> Optional[Transaction]:

        query = select(Transaction).where(
            Transaction.id == transaction_id
        )

        if lock:
            query = query.with_for_update()

        result = await db.execute(query)

        return result.scalar_one_or_none()

    # =========================================================
    # RECUPERER PAR REFERENCE
    # =========================================================

    async def get_by_reference(
        self,
        db: AsyncSession,
        reference: str,
        lock: bool = False,
    ) -> Optional[Transaction]:

        query = select(Transaction).where(
            Transaction.reference == reference
        )

        if lock:
            query = query.with_for_update()

        result = await db.execute(query)

        return result.scalar_one_or_none()

    # =========================================================
    # ENREGISTRER LE PAIEMENT MONEY FUSION
    # =========================================================

    async def attach_payment(
        self,
        db: AsyncSession,
        transaction_id: int,
        payment_token: str,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        if transaction.status not in [
            "pending_payment",
        ]:
            raise ValueError(
                "Cette transaction n'attend plus un paiement."
            )

        transaction.payment_reference = (
            payment_token
        )

        transaction.payment_status = "pending"

        await db.flush()

        return transaction

    # =========================================================
    # CONFIRMER LE PAIEMENT
    # =========================================================

    async def confirm_payment(
        self,
        db: AsyncSession,
        transaction_id: int,
        payment_reference: str,
        provider_fee: Optional[float] = None,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        # Idempotence :
        # si le paiement a déjà été confirmé,
        # on ne bloque pas les fonds une deuxième fois.
        if transaction.status in [
            "payment_confirmed",
            "waiting_admin",
            "assigned",
            "transfer_pending",
            "completed",
        ]:
            return transaction

        if transaction.status != "pending_payment":
            raise ValueError(
                "Cette transaction ne peut pas être confirmée."
            )

        if provider_fee is not None:
            transaction.provider_fee = money(
                provider_fee
            )

        transaction.payment_reference = (
            payment_reference
        )

        transaction.payment_status = "paid"

        transaction.status = "payment_confirmed"

        # Le montant réellement payé par l'acheteur.
        transaction.total_buyer_amount = (
            money(transaction.channel_price)
            + money(transaction.provider_fee)
        )

        await wallet_service.hold_funds(
            db=db,
            user_id=transaction.buyer_id,
            amount=float(
                transaction.total_buyer_amount
            ),
            reference=transaction.reference,
        )

        transaction.status = "waiting_admin"

        transaction.payment_confirmed_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        await db.flush()

        return transaction

    # =========================================================
    # PRENDRE UNE TRANSACTION EN CHARGE
    # =========================================================

    async def assign_admin(
        self,
        db: AsyncSession,
        transaction_id: int,
        admin_id: int,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        if transaction.status not in [
            "waiting_admin",
            "assigned",
        ]:
            raise ValueError(
                "Cette transaction ne peut pas "
                "être prise en charge."
            )

        # Si déjà assignée au même admin,
        # on retourne simplement la transaction.
        if (
            transaction.assigned_admin_id
            == admin_id
        ):
            return transaction

        # Une transaction déjà prise par quelqu'un
        # ne peut pas être récupérée silencieusement.
        if transaction.assigned_admin_id:
            raise ValueError(
                "Cette transaction est déjà prise "
                "en charge par un autre administrateur."
            )

        transaction.assigned_admin_id = admin_id
        transaction.status = "assigned"

        transaction.assigned_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        await db.flush()

        return transaction

    # =========================================================
    # DEMARRER LE TRANSFERT
    # =========================================================

    async def start_transfer(
        self,
        db: AsyncSession,
        transaction_id: int,
        admin_id: int,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        if (
            transaction.assigned_admin_id
            != admin_id
        ):
            raise ValueError(
                "Vous n'êtes pas l'administrateur "
                "assigné à cette transaction."
            )

        if transaction.status != "assigned":
            raise ValueError(
                "La transaction n'est pas prête "
                "pour le transfert."
            )

        transaction.status = "transfer_pending"

        transaction.transfer_started_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        await db.flush()

        return transaction

    # =========================================================
    # TERMINER LA TRANSACTION
    # =========================================================

    async def complete_transaction(
        self,
        db: AsyncSession,
        transaction_id: int,
        admin_id: int,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        if (
            transaction.assigned_admin_id
            != admin_id
        ):
            raise ValueError(
                "Vous n'êtes pas l'administrateur "
                "assigné à cette transaction."
            )

        if transaction.status not in [
            "transfer_pending",
        ]:
            raise ValueError(
                "La transaction n'est pas prête "
                "à être finalisée."
            )

        # Le vendeur reçoit le prix moins
        # la commission NexMarket.
        seller_amount = money(
            transaction.seller_amount
        )

        platform_fee = money(
            transaction.platform_fee
        )

        total_locked = money(
            transaction.total_buyer_amount
        )

        # Libère d'abord les fonds bloqués
        # de l'acheteur.
        await wallet_service.release_funds(
            db=db,
            user_id=transaction.buyer_id,
            amount=float(total_locked),
            reference=transaction.reference,
        )

        # Enregistre ensuite le revenu du vendeur.
        await wallet_service.add_sale_revenue(
            db=db,
            user_id=transaction.seller_id,
            amount=float(seller_amount),
            reference=transaction.reference,
        )

        # La commission est enregistrée séparément.
        #
        # Le PlatformWallet sera alimenté par le service
        # de plateforme lorsqu'il sera intégré.
        if platform_fee > 0:
            logger.info(
                "Commission NexMarket à enregistrer : %s",
                platform_fee,
            )

        transaction.status = "completed"

        transaction.completed_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        transaction.transfer_completed_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        await db.flush()

        return transaction

    # =========================================================
    # ANNULER
    # =========================================================

    async def cancel_transaction(
        self,
        db: AsyncSession,
        transaction_id: int,
        reason: Optional[str] = None,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        if transaction.status == "completed":
            raise ValueError(
                "Une transaction terminée ne peut "
                "pas être annulée."
            )

        # Si l'argent a déjà été bloqué,
        # il faut le rendre au buyer.
        if transaction.status in [
            "payment_confirmed",
            "waiting_admin",
            "assigned",
            "transfer_pending",
            "disputed",
        ]:

            total_locked = money(
                transaction.total_buyer_amount
            )

            if total_locked > 0:

                wallet = await wallet_service.get_wallet(
                    db,
                    transaction.buyer_id,
                    create_if_missing=False,
                )

                if wallet:

                    blocked = money(
                        wallet.blocked_balance
                    )

                    # On ne libère que si les fonds
                    # sont effectivement présents.
                    if blocked >= total_locked:
                        await wallet_service.release_funds(
                            db=db,
                            user_id=transaction.buyer_id,
                            amount=float(total_locked),
                            reference=transaction.reference,
                        )

        transaction.status = "cancelled"

        if reason:
            transaction.cancellation_reason = (
                reason[:2000]
            )

        transaction.cancelled_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        await db.flush()

        return transaction

    # =========================================================
    # LANCER UN LITIGE
    # =========================================================

    async def dispute_transaction(
        self,
        db: AsyncSession,
        transaction_id: int,
        user_id: int,
        reason: str,
    ) -> Transaction:

        transaction = await self.get_transaction(
            db,
            transaction_id,
            lock=True,
        )

        if not transaction:
            raise ValueError(
                "Transaction introuvable."
            )

        if user_id not in [
            transaction.buyer_id,
            transaction.seller_id,
        ]:
            raise ValueError(
                "Vous ne participez pas à cette transaction."
            )

        if transaction.status not in [
            "payment_confirmed",
            "waiting_admin",
            "assigned",
            "transfer_pending",
        ]:
            raise ValueError(
                "Cette transaction ne peut pas "
                "être mise en litige."
            )

        transaction.status = "disputed"

        transaction.dispute_reason = (
            reason[:2000]
        )

        transaction.dispute_opened_at = (
            __import__("datetime")
            .datetime.utcnow()
        )

        await db.flush()

        return transaction


# =============================================================
# INSTANCE UNIQUE
# =============================================================

transaction_service = TransactionService()