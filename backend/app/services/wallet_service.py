from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import Wallet, WalletOperation


class WalletServiceError(Exception):
    """Erreur métier liée au wallet."""


class WalletService:
    """
    Gestion du wallet utilisateur.

    available_balance :
        argent disponible pour l'utilisateur.

    blocked_balance :
        argent temporairement bloqué.

    Les commissions NexMarket ne doivent PAS être enregistrées
    dans le wallet utilisateur. Elles sont gérées séparément
    par PlatformWallet / PlatformLedger.
    """

    def __init__(
        self,
        db: AsyncSession,
    ):
        self.db = db

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _money(
        amount: Decimal | int | float | str,
    ) -> Decimal:
        return Decimal(
            str(amount)
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _reference(
        prefix: str,
    ) -> str:
        return (
            f"{prefix}-"
            f"{uuid4().hex[:16].upper()}"
        )

    async def get_wallet(
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
            raise WalletServiceError(
                "Wallet introuvable."
            )

        return wallet

    # ========================================================
    # BALANCE
    # ========================================================

    async def get_balance(
        self,
        user_id: int,
    ) -> dict:
        wallet = await self.get_wallet(
            user_id
        )

        return {
            "available_balance": wallet.available_balance,
            "blocked_balance": wallet.blocked_balance,
            "total_revenue": wallet.total_revenue,
            "currency": wallet.currency,
        }

    # ========================================================
    # CREDIT
    # ========================================================

    async def credit(
        self,
        *,
        user_id: int,
        amount: Decimal,
        reference: str | None = None,
        operation_type: str = "deposit",
        provider_reference: str | None = None,
        description: str | None = None,
    ) -> Wallet:
        """
        Ajoute un montant au solde disponible.

        Utilisé notamment après confirmation réelle
        d'un dépôt JessiKaPay.
        """

        amount = self._money(amount)

        if amount <= 0:
            raise WalletServiceError(
                "Le montant doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            user_id
        )

        operation_reference = (
            reference
            or self._reference("WAL-CREDIT")
        )

        # Protection contre un webhook ou événement
        # traité deux fois.
        existing = await self.db.execute(
            select(WalletOperation).where(
                WalletOperation.reference
                == operation_reference
            )
        )

        if existing.scalar_one_or_none() is not None:
            raise WalletServiceError(
                "Cette opération a déjà été enregistrée."
            )

        wallet.available_balance = (
            self._money(wallet.available_balance)
            + amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type=operation_type,
            amount=amount,
            currency=wallet.currency,
            status="completed",
            provider_reference=provider_reference,
            reference=operation_reference,
            description=description,
        )

        self.db.add(operation)

        await self.db.commit()
        await self.db.refresh(wallet)

        return wallet

    # ========================================================
    # DEBIT
    # ========================================================

    async def debit(
        self,
        *,
        user_id: int,
        amount: Decimal,
        reference: str | None = None,
        operation_type: str = "debit",
        provider_reference: str | None = None,
        description: str | None = None,
    ) -> Wallet:
        """
        Retire un montant du solde disponible.
        """

        amount = self._money(amount)

        if amount <= 0:
            raise WalletServiceError(
                "Le montant doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            user_id
        )

        available = self._money(
            wallet.available_balance
        )

        if available < amount:
            raise WalletServiceError(
                "Solde disponible insuffisant."
            )

        operation_reference = (
            reference
            or self._reference("WAL-DEBIT")
        )

        existing = await self.db.execute(
            select(WalletOperation).where(
                WalletOperation.reference
                == operation_reference
            )
        )

        if existing.scalar_one_or_none() is not None:
            raise WalletServiceError(
                "Cette opération a déjà été enregistrée."
            )

        wallet.available_balance = (
            available - amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type=operation_type,
            amount=amount,
            currency=wallet.currency,
            status="completed",
            provider_reference=provider_reference,
            reference=operation_reference,
            description=description,
        )

        self.db.add(operation)

        await self.db.commit()
        await self.db.refresh(wallet)

        return wallet

    # ========================================================
    # BLOCK FUNDS
    # ========================================================

    async def block(
        self,
        *,
        user_id: int,
        amount: Decimal,
        reference: str,
        description: str | None = None,
    ) -> Wallet:
        """
        Déplace de l'argent disponible vers l'argent bloqué.

        Utilisé pour l'escrow NexMarket.
        """

        amount = self._money(amount)

        if amount <= 0:
            raise WalletServiceError(
                "Le montant doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            user_id
        )

        available = self._money(
            wallet.available_balance
        )

        if available < amount:
            raise WalletServiceError(
                "Solde disponible insuffisant."
            )

        existing = await self.db.execute(
            select(WalletOperation).where(
                WalletOperation.reference
                == reference
            )
        )

        if existing.scalar_one_or_none() is not None:
            raise WalletServiceError(
                "Cette opération existe déjà."
            )

        wallet.available_balance = (
            available - amount
        )

        wallet.blocked_balance = (
            self._money(wallet.blocked_balance)
            + amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="escrow_block",
            amount=amount,
            currency=wallet.currency,
            status="completed",
            reference=reference,
            description=description,
        )

        self.db.add(operation)

        await self.db.commit()
        await self.db.refresh(wallet)

        return wallet

    # ========================================================
    # RELEASE BLOCKED FUNDS
    # ========================================================

    async def release_blocked(
        self,
        *,
        user_id: int,
        amount: Decimal,
        reference: str,
        description: str | None = None,
    ) -> Wallet:
        """
        Libère des fonds précédemment bloqués.

        Le montant retourne dans le solde disponible.
        """

        amount = self._money(amount)

        if amount <= 0:
            raise WalletServiceError(
                "Le montant doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            user_id
        )

        blocked = self._money(
            wallet.blocked_balance
        )

        if blocked < amount:
            raise WalletServiceError(
                "Fonds bloqués insuffisants."
            )

        existing = await self.db.execute(
            select(WalletOperation).where(
                WalletOperation.reference
                == reference
            )
        )

        if existing.scalar_one_or_none() is not None:
            raise WalletServiceError(
                "Cette opération existe déjà."
            )

        wallet.blocked_balance = (
            blocked - amount
        )

        wallet.available_balance = (
            self._money(wallet.available_balance)
            + amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="escrow_release",
            amount=amount,
            currency=wallet.currency,
            status="completed",
            reference=reference,
            description=description,
        )

        self.db.add(operation)

        await self.db.commit()
        await self.db.refresh(wallet)

        return wallet

    # ========================================================
    # CONSUME BLOCKED FUNDS
    # ========================================================

    async def consume_blocked(
        self,
        *,
        user_id: int,
        amount: Decimal,
        reference: str,
        description: str | None = None,
    ) -> Wallet:
        """
        Consomme définitivement des fonds bloqués.

        Utilisé lorsqu'une transaction est validée et que
        les fonds doivent quitter le wallet acheteur.
        """

        amount = self._money(amount)

        if amount <= 0:
            raise WalletServiceError(
                "Le montant doit être supérieur à zéro."
            )

        wallet = await self.get_wallet(
            user_id
        )

        blocked = self._money(
            wallet.blocked_balance
        )

        if blocked < amount:
            raise WalletServiceError(
                "Fonds bloqués insuffisants."
            )

        existing = await self.db.execute(
            select(WalletOperation).where(
                WalletOperation.reference
                == reference
            )
        )

        if existing.scalar_one_or_none() is not None:
            raise WalletServiceError(
                "Cette opération existe déjà."
            )

        wallet.blocked_balance = (
            blocked - amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="escrow_consumed",
            amount=amount,
            currency=wallet.currency,
            status="completed",
            reference=reference,
            description=description,
        )

        self.db.add(operation)

        await self.db.commit()
        await self.db.refresh(wallet)

        return wallet

    # ========================================================
    # OPERATION HISTORY
    # ========================================================

    async def get_operations(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> list[WalletOperation]:
        """
        Retourne l'historique financier du wallet.
        """

        if limit < 1:
            limit = 1

        if limit > 100:
            limit = 100

        wallet = await self.get_wallet(
            user_id
        )

        result = await self.db.execute(
            select(WalletOperation)
            .where(
                WalletOperation.wallet_id
                == wallet.id
            )
            .order_by(
                WalletOperation.created_at.desc()
            )
            .limit(limit)
        )

        return list(result.scalars().all())
