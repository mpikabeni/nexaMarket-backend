from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import Wallet, WalletOperation
from app.services.moneyfusion_service import (
    MoneyFusionError,
    moneyfusion_service,
)


logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


def money(value) -> Decimal:
    """
    Convertit une valeur en Decimal avec 2 décimales.
    """
    return Decimal(str(value or 0)).quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


class WalletService:
    """
    Gestion centralisée des portefeuilles NexMarket.

    Soldes :
    - available_balance : argent disponible
    - blocked_balance   : argent temporairement bloqué
    - revenue_balance   : revenus du vendeur
    """

    # =========================================================
    # RECUPERER LE WALLET
    # =========================================================

    async def get_wallet(
        self,
        db: AsyncSession,
        user_id: int,
        create_if_missing: bool = True,
    ) -> Optional[Wallet]:

        result = await db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .with_for_update()
        )

        wallet = result.scalar_one_or_none()

        if wallet:
            return wallet

        if not create_if_missing:
            return None

        wallet = Wallet(
            user_id=user_id,
            available_balance=Decimal("0"),
            blocked_balance=Decimal("0"),
            revenue_balance=Decimal("0"),
        )

        db.add(wallet)

        await db.flush()

        return wallet

    # =========================================================
    # SOLDE
    # =========================================================

    async def get_balance(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> dict:

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=True,
        )

        return {
            "available": money(wallet.available_balance),
            "blocked": money(wallet.blocked_balance),
            "revenue": money(wallet.revenue_balance),
            "currency": "XAF",
        }

    # =========================================================
    # ENREGISTRER UNE OPERATION
    # =========================================================

    async def _create_operation(
        self,
        db: AsyncSession,
        wallet: Wallet,
        operation_type: str,
        amount: Decimal,
        reference: Optional[str] = None,
        provider_reference: Optional[str] = None,
        description: Optional[str] = None,
    ) -> WalletOperation:

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type=operation_type,
            amount=money(amount),
            reference=reference,
            provider_reference=provider_reference,
            description=description,
        )

        db.add(operation)

        await db.flush()

        return operation

    # =========================================================
    # DEPOT
    # =========================================================

    async def create_deposit(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        customer_name: str,
        customer_phone: str,
        reference: str,
    ) -> dict:

        amount_decimal = money(amount)

        if amount_decimal <= 0:
            raise ValueError(
                "Le montant du dépôt doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=True,
        )

        # Le dépôt n'est PAS ajouté au solde ici.
        #
        # Il doit d'abord être payé et confirmé
        # par Money Fusion.

        payment = await moneyfusion_service.create_payment(
            amount=float(amount_decimal),
            article_name="Dépôt NexMarket",
            customer_name=customer_name,
            customer_phone=customer_phone,
            user_id=user_id,
            order_id=0,
        )

        token = moneyfusion_service.extract_payment_token(
            payment
        )

        if not token:
            logger.error(
                "Money Fusion n'a pas fourni de token "
                "pour le dépôt %s",
                reference,
            )

            raise MoneyFusionError(
                "Money Fusion n'a pas retourné de token."
            )

        return {
            "status": "pending",
            "reference": reference,
            "token": token,
            "payment": payment,
            "amount": amount_decimal,
        }

    # =========================================================
    # CONFIRMER UN DEPOT
    # =========================================================

    async def confirm_deposit(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
        provider_reference: Optional[str] = None,
    ) -> Wallet:

        amount_decimal = money(amount)

        if amount_decimal <= 0:
            raise ValueError(
                "Le montant du dépôt doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=True,
        )

        wallet.available_balance = (
            money(wallet.available_balance)
            + amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="deposit",
            amount=amount_decimal,
            reference=reference,
            provider_reference=provider_reference,
            description="Dépôt Money Fusion confirmé",
        )

        await db.flush()

        return wallet

    # =========================================================
    # VERIFIER UN DEPOT MONEY FUSION
    # =========================================================

    async def verify_deposit(
        self,
        db: AsyncSession,
        user_id: int,
        token: str,
        reference: str,
    ) -> dict:

        payment_status = (
            await moneyfusion_service.get_payment_status(
                token
            )
        )

        status = (
            moneyfusion_service.extract_payment_status(
                payment_status
            )
        )

        amount = (
            moneyfusion_service.extract_payment_amount(
                payment_status
            )
        )

        if status != "paid":
            return {
                "status": status or "pending",
                "confirmed": False,
                "reference": reference,
            }

        if not amount:
            raise MoneyFusionError(
                "Montant du paiement introuvable."
            )

        # Le webhook devra normalement assurer
        # l'idempotence avec sa référence/token.
        #
        # Cette fonction retourne seulement la
        # confirmation afin que la route/webhook
        # puisse appliquer le dépôt.

        return {
            "status": "paid",
            "confirmed": True,
            "reference": reference,
            "token": token,
            "amount": money(amount),
        }

    # =========================================================
    # RETRAIT
    # =========================================================

    async def request_withdrawal(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        country_code: str,
        phone: str,
        withdraw_mode: str,
        reference: str,
    ) -> dict:

        amount_decimal = money(amount)

        if amount_decimal <= 0:
            raise ValueError(
                "Le montant du retrait doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=False,
        )

        if not wallet:
            raise ValueError(
                "Portefeuille introuvable."
            )

        available = money(
            wallet.available_balance
        )

        if available < amount_decimal:
            raise ValueError(
                "Solde disponible insuffisant."
            )

        # On réserve l'argent avant d'appeler
        # Money Fusion.
        wallet.available_balance = (
            available - amount_decimal
        )

        wallet.blocked_balance = (
            money(wallet.blocked_balance)
            + amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="withdrawal",
            amount=amount_decimal,
            reference=reference,
            description="Retrait Money Fusion en attente",
        )

        await db.flush()

        try:

            withdrawal = (
                await moneyfusion_service.create_withdrawal(
                    amount=float(amount_decimal),
                    country_code=country_code,
                    phone=phone,
                    withdraw_mode=withdraw_mode,
                )
            )

        except Exception:

            # Si Money Fusion refuse immédiatement
            # la demande, on remet les fonds disponibles.

            wallet.available_balance = (
                money(wallet.available_balance)
                + amount_decimal
            )

            wallet.blocked_balance = max(
                Decimal("0"),
                money(wallet.blocked_balance)
                - amount_decimal,
            )

            await db.flush()

            raise

        return {
            "status": "pending",
            "reference": reference,
            "amount": amount_decimal,
            "withdrawal": withdrawal,
        }

    # =========================================================
    # RETRAIT TERMINE
    # =========================================================

    async def complete_withdrawal(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
        provider_reference: Optional[str] = None,
    ) -> Wallet:

        amount_decimal = money(amount)

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=False,
        )

        if not wallet:
            raise ValueError(
                "Portefeuille introuvable."
            )

        blocked = money(
            wallet.blocked_balance
        )

        if blocked < amount_decimal:
            raise ValueError(
                "Montant bloqué insuffisant."
            )

        wallet.blocked_balance = (
            blocked - amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="withdrawal",
            amount=amount_decimal,
            reference=reference,
            provider_reference=provider_reference,
            description="Retrait Money Fusion terminé",
        )

        await db.flush()

        return wallet

    # =========================================================
    # RETRAIT ANNULE / ECHOUE
    # =========================================================

    async def cancel_withdrawal(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
        provider_reference: Optional[str] = None,
    ) -> Wallet:

        amount_decimal = money(amount)

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=False,
        )

        if not wallet:
            raise ValueError(
                "Portefeuille introuvable."
            )

        blocked = money(
            wallet.blocked_balance
        )

        if blocked < amount_decimal:
            raise ValueError(
                "Montant bloqué insuffisant."
            )

        wallet.blocked_balance = (
            blocked - amount_decimal
        )

        wallet.available_balance = (
            money(wallet.available_balance)
            + amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="refund",
            amount=amount_decimal,
            reference=reference,
            provider_reference=provider_reference,
            description="Retrait Money Fusion annulé",
        )

        await db.flush()

        return wallet

    # =========================================================
    # BLOQUER DES FONDS POUR UNE TRANSACTION
    # =========================================================

    async def hold_funds(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
    ) -> Wallet:

        amount_decimal = money(amount)

        if amount_decimal <= 0:
            raise ValueError(
                "Le montant à bloquer doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=False,
        )

        if not wallet:
            raise ValueError(
                "Portefeuille introuvable."
            )

        available = money(
            wallet.available_balance
        )

        if available < amount_decimal:
            raise ValueError(
                "Solde disponible insuffisant."
            )

        wallet.available_balance = (
            available - amount_decimal
        )

        wallet.blocked_balance = (
            money(wallet.blocked_balance)
            + amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="transaction_hold",
            amount=amount_decimal,
            reference=reference,
            description="Fonds bloqués pour une transaction",
        )

        await db.flush()

        return wallet

    # =========================================================
    # LIBERER DES FONDS
    # =========================================================

    async def release_funds(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
    ) -> Wallet:

        amount_decimal = money(amount)

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=False,
        )

        if not wallet:
            raise ValueError(
                "Portefeuille introuvable."
            )

        blocked = money(
            wallet.blocked_balance
        )

        if blocked < amount_decimal:
            raise ValueError(
                "Montant bloqué insuffisant."
            )

        wallet.blocked_balance = (
            blocked - amount_decimal
        )

        wallet.available_balance = (
            money(wallet.available_balance)
            + amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="transaction_release",
            amount=amount_decimal,
            reference=reference,
            description="Fonds libérés",
        )

        await db.flush()

        return wallet

    # =========================================================
    # REVENUS VENDEUR
    # =========================================================

    async def add_sale_revenue(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
    ) -> Wallet:

        amount_decimal = money(amount)

        if amount_decimal <= 0:
            raise ValueError(
                "Le revenu doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=True,
        )

        wallet.available_balance = (
            money(wallet.available_balance)
            + amount_decimal
        )

        wallet.revenue_balance = (
            money(wallet.revenue_balance)
            + amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="sale_revenue",
            amount=amount_decimal,
            reference=reference,
            description="Revenu d'une vente NexMarket",
        )

        await db.flush()

        return wallet

    # =========================================================
    # COMMISSION NEXMARKET
    # =========================================================

    async def record_platform_fee(
        self,
        db: AsyncSession,
        user_id: int,
        amount: float,
        reference: str,
    ) -> Wallet:

        amount_decimal = money(amount)

        wallet = await self.get_wallet(
            db,
            user_id,
            create_if_missing=False,
        )

        if not wallet:
            raise ValueError(
                "Portefeuille introuvable."
            )

        blocked = money(
            wallet.blocked_balance
        )

        if blocked < amount_decimal:
            raise ValueError(
                "Fonds bloqués insuffisants pour "
                "prélever la commission."
            )

        wallet.blocked_balance = (
            blocked - amount_decimal
        )

        await self._create_operation(
            db=db,
            wallet=wallet,
            operation_type="platform_fee",
            amount=amount_decimal,
            reference=reference,
            description="Commission NexMarket",
        )

        await db.flush()

        return wallet


# =============================================================
# INSTANCE UNIQUE
# =============================================================

wallet_service = WalletService()