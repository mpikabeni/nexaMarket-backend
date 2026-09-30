from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.wallet import Wallet, WalletOperation
from app.models.withdrawal import Withdrawal
from app.services.jessikapay_service import (
    JessiKaPayError,
    JessiKaPayService,
)


class WithdrawalServiceError(Exception):
    """Erreur métier liée aux retraits."""


class WithdrawalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.jessikapay = JessiKaPayService()

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _money(value) -> Decimal:
        return Decimal(str(value)).quantize(Decimal("0.01"))

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _reference() -> str:
        return f"NMX-WD-{uuid4().hex[:16].upper()}"

    async def _get_user(self, user_id: int) -> User:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise WithdrawalServiceError(
                "Utilisateur introuvable."
            )

        if not user.is_active:
            raise WithdrawalServiceError(
                "Le compte utilisateur est désactivé."
            )

        return user

    async def _get_wallet(self, user_id: int) -> Wallet:
        result = await self.db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .with_for_update()
        )

        wallet = result.scalar_one_or_none()

        if not wallet:
            raise WithdrawalServiceError(
                "Portefeuille introuvable."
            )

        return wallet

    async def _get_withdrawal(
        self,
        withdrawal_id: int,
    ) -> Withdrawal:
        result = await self.db.execute(
            select(Withdrawal)
            .where(Withdrawal.id == withdrawal_id)
        )

        withdrawal = result.scalar_one_or_none()

        if not withdrawal:
            raise WithdrawalServiceError(
                "Demande de retrait introuvable."
            )

        return withdrawal

    # ============================================================
    # CREATE WITHDRAWAL
    # ============================================================

    async def create_withdrawal(
        self,
        *,
        user_id: int,
        amount: Decimal,
        currency: str,
        jp_number: str,
    ) -> Withdrawal:

        user = await self._get_user(user_id)
        wallet = await self._get_wallet(user.id)

        amount = self._money(amount)
        currency = currency.upper().strip()
        jp_number = jp_number.strip()

        if amount <= 0:
            raise WithdrawalServiceError(
                "Le montant du retrait doit être supérieur à 0."
            )

        if not jp_number:
            raise WithdrawalServiceError(
                "Le numéro JessiKaPay est obligatoire."
            )

        # Pour le moment, aucun taux de change n'est inventé.
        # Les retraits sont effectués en XAF selon la documentation
        # JessiKaPay fournie.
        if currency != "XAF":
            raise WithdrawalServiceError(
                "Les retraits sont actuellement disponibles uniquement en XAF."
            )

        wallet_currency = (
            wallet.currency.upper()
            if wallet.currency
            else "XAF"
        )

        if wallet_currency != currency:
            raise WithdrawalServiceError(
                "La devise du portefeuille ne correspond pas "
                "à la devise du retrait."
            )

        available = self._money(wallet.available_balance)

        if amount > available:
            raise WithdrawalServiceError(
                "Solde disponible insuffisant."
            )

        reference = self._reference()

        # --------------------------------------------------------
        # BLOQUER LE MONTANT
        # --------------------------------------------------------

        wallet.available_balance = available - amount
        wallet.blocked_balance = (
            self._money(wallet.blocked_balance) + amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="withdrawal_block",
            amount=amount,
            currency=currency,
            status="blocked",
            reference=reference,
            description=(
                f"Montant bloqué pour le retrait {reference}"
            ),
        )

        self.db.add(operation)

        withdrawal = Withdrawal(
            user_id=user.id,
            reference=reference,
            amount=amount,
            currency=currency,
            jessikapay_jp_number=jp_number,
            status="pending",
        )

        self.db.add(withdrawal)

        await self.db.commit()
        await self.db.refresh(withdrawal)

        return withdrawal

    # ============================================================
    # PROCESS PAYOUT
    # ============================================================

    async def process_withdrawal(
        self,
        withdrawal_id: int,
    ) -> Withdrawal:

        withdrawal = await self._get_withdrawal(
            withdrawal_id
        )

        if withdrawal.status != "pending":
            raise WithdrawalServiceError(
                "Cette demande de retrait ne peut plus être traitée."
            )

        if withdrawal.currency.upper() != "XAF":
            raise WithdrawalServiceError(
                "Les retraits JessiKaPay sont actuellement traités en XAF."
            )

        # --------------------------------------------------------
        # PASSAGE EN PROCESSING
        # --------------------------------------------------------

        withdrawal.status = "processing"
        withdrawal.processed_at = self._now()

        await self.db.commit()

        payout_reference = (
            f"NMX-PAYOUT-{withdrawal.reference}"
        )

        try:
            response = await self.jessikapay.create_payout(
                jp_number=withdrawal.jessikapay_jp_number,
                amount=int(withdrawal.amount),
                reference=payout_reference,
                description=(
                    f"Retrait NexMarket {withdrawal.reference}"
                ),
            )

        except JessiKaPayError as exc:
            await self._fail_withdrawal(
                withdrawal,
                str(exc),
            )
            raise WithdrawalServiceError(
                f"Le paiement JessiKaPay a échoué : {exc}"
            ) from exc

        except Exception as exc:
            await self._fail_withdrawal(
                withdrawal,
                "Erreur inattendue lors de l'appel JessiKaPay.",
            )
            raise WithdrawalServiceError(
                "Impossible de traiter le retrait pour le moment."
            ) from exc

        transaction_id = response.get(
            "transaction_id"
        )

        if not transaction_id:
            await self._fail_withdrawal(
                withdrawal,
                "JessiKaPay n'a pas retourné de transaction_id.",
            )

            raise WithdrawalServiceError(
                "Réponse JessiKaPay invalide."
            )

        withdrawal.jessikapay_transaction_id = (
            str(transaction_id)
        )

        withdrawal.status = "payout_sent"

        await self.db.commit()
        await self.db.refresh(withdrawal)

        return withdrawal

    # ============================================================
    # CONFIRM CREDIT.COMPLETED
    # ============================================================

    async def confirm_payout(
        self,
        *,
        transaction_id: str,
        amount: Decimal,
        reference: str | None = None,
    ) -> Withdrawal:

        result = await self.db.execute(
            select(Withdrawal)
            .where(
                Withdrawal.jessikapay_transaction_id
                == str(transaction_id)
            )
        )

        withdrawal = result.scalar_one_or_none()

        if not withdrawal:
            raise WithdrawalServiceError(
                "Retrait correspondant introuvable."
            )

        if withdrawal.status == "completed":
            return withdrawal

        if withdrawal.status != "payout_sent":
            raise WithdrawalServiceError(
                "Ce retrait n'attend pas de confirmation JessiKaPay."
            )

        provider_amount = self._money(amount)
        expected_amount = self._money(
            withdrawal.amount
        )

        if provider_amount != expected_amount:
            raise WithdrawalServiceError(
                "Le montant du webhook JessiKaPay "
                "ne correspond pas au retrait."
            )

        if reference:
            expected_reference = (
                f"NMX-PAYOUT-{withdrawal.reference}"
            )

            if reference != expected_reference:
                raise WithdrawalServiceError(
                    "La référence du webhook "
                    "ne correspond pas au retrait."
                )

        wallet = await self._get_wallet(
            withdrawal.user_id
        )

        blocked = self._money(
            wallet.blocked_balance
        )

        if blocked < expected_amount:
            raise WithdrawalServiceError(
                "Le solde bloqué du portefeuille est insuffisant."
            )

        # --------------------------------------------------------
        # CONSOMMER LE MONTANT BLOQUÉ
        # --------------------------------------------------------

        wallet.blocked_balance = (
            blocked - expected_amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="withdrawal_completed",
            amount=expected_amount,
            currency=withdrawal.currency,
            status="completed",
            provider_reference=str(
                transaction_id
            ),
            reference=withdrawal.reference,
            description=(
                f"Retrait confirmé {withdrawal.reference}"
            ),
        )

        self.db.add(operation)

        withdrawal.status = "completed"
        withdrawal.completed_at = self._now()

        await self.db.commit()
        await self.db.refresh(withdrawal)

        return withdrawal

    # ============================================================
    # FAIL WITHDRAWAL
    # ============================================================

    async def _fail_withdrawal(
        self,
        withdrawal: Withdrawal,
        reason: str,
    ) -> None:

        wallet = await self._get_wallet(
            withdrawal.user_id
        )

        amount = self._money(
            withdrawal.amount
        )

        blocked = self._money(
            wallet.blocked_balance
        )

        if blocked >= amount:
            wallet.blocked_balance = (
                blocked - amount
            )

        wallet.available_balance = (
            self._money(wallet.available_balance)
            + amount
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="withdrawal_release",
            amount=amount,
            currency=withdrawal.currency,
            status="released",
            reference=f"{withdrawal.reference}-RELEASE",
            description=(
                f"Libération du montant du retrait "
                f"{withdrawal.reference}"
            ),
        )

        self.db.add(operation)

        withdrawal.status = "failed"
        withdrawal.failure_reason = reason
        withdrawal.completed_at = None

        await self.db.commit()

    # ============================================================
    # REJECT WITHDRAWAL
    # ============================================================

    async def reject_withdrawal(
        self,
        withdrawal_id: int,
        admin_id: int,
        reason: str,
    ) -> Withdrawal:

        withdrawal = await self._get_withdrawal(
            withdrawal_id
        )

        if withdrawal.status not in (
            "pending",
            "processing",
        ):
            raise WithdrawalServiceError(
                "Ce retrait ne peut plus être rejeté."
            )

        wallet = await self._get_wallet(
            withdrawal.user_id
        )

        amount = self._money(
            withdrawal.amount
        )

        blocked = self._money(
            wallet.blocked_balance
        )

        if blocked < amount:
            raise WithdrawalServiceError(
                "Le solde bloqué est insuffisant."
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
            operation_type="withdrawal_rejected",
            amount=amount,
            currency=withdrawal.currency,
            status="released",
            reference=f"{withdrawal.reference}-REJECT",
            description=(
                f"Retrait rejeté {withdrawal.reference}"
            ),
        )

        self.db.add(operation)

        withdrawal.status = "rejected"
        withdrawal.reviewed_by_admin_id = admin_id
        withdrawal.admin_note = reason
        withdrawal.failure_reason = reason
        withdrawal.rejected_at = self._now()

        await self.db.commit()
        await self.db.refresh(withdrawal)

        return withdrawal

    # ============================================================
    # CANCEL WITHDRAWAL
    # ============================================================

    async def cancel_withdrawal(
        self,
        withdrawal_id: int,
        user_id: int,
    ) -> Withdrawal:

        withdrawal = await self._get_withdrawal(
            withdrawal_id
        )

        if withdrawal.user_id != user_id:
            raise WithdrawalServiceError(
                "Accès refusé."
            )

        if withdrawal.status != "pending":
            raise WithdrawalServiceError(
                "Seule une demande en attente peut être annulée."
            )

        wallet = await self._get_wallet(
            user_id
        )

        amount = self._money(
            withdrawal.amount
        )

        blocked = self._money(
            wallet.blocked_balance
        )

        if blocked < amount:
            raise WithdrawalServiceError(
                "Le solde bloqué est insuffisant."
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
            operation_type="withdrawal_cancelled",
            amount=amount,
            currency=withdrawal.currency,
            status="released",
            reference=f"{withdrawal.reference}-CANCEL",
            description=(
                f"Retrait annulé {withdrawal.reference}"
            ),
        )

        self.db.add(operation)

        withdrawal.status = "cancelled"
        withdrawal.cancelled_at = self._now()

        await self.db.commit()
        await self.db.refresh(withdrawal)

        return withdrawal
