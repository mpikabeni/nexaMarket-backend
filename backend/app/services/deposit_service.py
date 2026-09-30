from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.deposit import Deposit
from app.models.user import User
from app.models.wallet import Wallet, WalletOperation
from app.services.jessikapay_service import (
    JessiKaPayError,
    JessiKaPayService,
)


class DepositServiceError(Exception):
    """Erreur métier liée aux dépôts."""


class DepositService:
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
        return f"NMX-DEP-{uuid4().hex[:16].upper()}"

    async def _get_user(self, user_id: int) -> User:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )

        user = result.scalar_one_or_none()

        if not user:
            raise DepositServiceError(
                "Utilisateur introuvable."
            )

        if not user.is_active:
            raise DepositServiceError(
                "Le compte utilisateur est désactivé."
            )

        return user

    async def _get_wallet(
        self,
        user_id: int,
    ) -> Wallet:

        result = await self.db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .with_for_update()
        )

        wallet = result.scalar_one_or_none()

        if not wallet:
            raise DepositServiceError(
                "Portefeuille introuvable."
            )

        return wallet

    async def _get_deposit(
        self,
        deposit_id: int,
    ) -> Deposit:

        result = await self.db.execute(
            select(Deposit).where(
                Deposit.id == deposit_id
            )
        )

        deposit = result.scalar_one_or_none()

        if not deposit:
            raise DepositServiceError(
                "Dépôt introuvable."
            )

        return deposit

    # ============================================================
    # CREATE DEPOSIT
    # ============================================================

    async def create_deposit(
        self,
        *,
        user_id: int,
        amount: Decimal,
        country: str,
        phone: str,
        currency: str = "XAF",
    ) -> Deposit:

        user = await self._get_user(user_id)

        amount = self._money(amount)
        currency = currency.upper().strip()
        country = country.upper().strip()
        phone = phone.strip()

        if amount <= 0:
            raise DepositServiceError(
                "Le montant du dépôt doit être supérieur à 0."
            )

        if currency != "XAF":
            raise DepositServiceError(
                "Les dépôts sont actuellement disponibles uniquement en XAF."
            )

        if not country:
            raise DepositServiceError(
                "Le pays est obligatoire."
            )

        if not phone:
            raise DepositServiceError(
                "Le numéro de téléphone est obligatoire."
            )

        reference = self._reference()

        try:
            response = (
                await self.jessikapay.create_deposit_request(
                    telegram_id=user.telegram_id,
                    name=(
                        user.first_name
                        or user.username
                        or f"User {user.telegram_id}"
                    ),
                    country=country,
                    phone=phone,
                    amount=int(amount),
                    reference=reference,
                )
            )

        except JessiKaPayError as exc:
            raise DepositServiceError(
                f"Impossible de créer le dépôt : {exc}"
            ) from exc

        request_id = response.get("request_id")

        if not request_id:
            raise DepositServiceError(
                "JessiKaPay n'a pas retourné de request_id."
            )

        deposit = Deposit(
            user_id=user.id,
            reference=reference,
            amount=amount,
            currency=currency,
            country=country,
            phone=phone,
            jessikapay_request_id=str(request_id),
            jessikapay_code=response.get("code"),
            payment_link=response.get("payment_link"),
            status=response.get(
                "status",
                "pending",
            ),
            expires_at=self._parse_datetime(
                response.get("expires_at")
            ),
        )

        self.db.add(deposit)

        await self.db.commit()
        await self.db.refresh(deposit)

        return deposit

    # ============================================================
    # GET PROVIDER STATUS
    # ============================================================

    async def refresh_deposit_status(
        self,
        deposit_id: int,
    ) -> Deposit:

        deposit = await self._get_deposit(
            deposit_id
        )

        if deposit.status == "paid":
            return deposit

        try:
            response = (
                await self.jessikapay.get_deposit_status(
                    deposit.jessikapay_request_id
                )
            )

        except JessiKaPayError as exc:
            raise DepositServiceError(
                f"Impossible de vérifier le dépôt : {exc}"
            ) from exc

        provider_status = (
            response.get("status")
            or deposit.status
        )

        deposit.status = provider_status

        if response.get("expires_at"):
            deposit.expires_at = self._parse_datetime(
                response.get("expires_at")
            )

        if provider_status in (
            "failed",
            "expired",
            "cancelled",
        ):
            deposit.failure_reason = (
                response.get("message")
                or response.get("reason")
                or f"Dépôt {provider_status}."
            )

        if provider_status == "paid":
            await self._credit_deposit(
                deposit,
                provider_response=response,
            )
        else:
            await self.db.commit()
            await self.db.refresh(deposit)

        return deposit

    # ============================================================
    # CONFIRM WEBHOOK
    # ============================================================

    async def confirm_webhook(
        self,
        *,
        request_id: str,
        amount: Decimal,
        commission_amount: Decimal | None = None,
        net_amount_credited: Decimal | None = None,
        event_id: str | None = None,
    ) -> Deposit:

        result = await self.db.execute(
            select(Deposit)
            .where(
                Deposit.jessikapay_request_id
                == str(request_id)
            )
            .with_for_update()
        )

        deposit = result.scalar_one_or_none()

        if not deposit:
            raise DepositServiceError(
                "Dépôt correspondant introuvable."
            )

        # --------------------------------------------------------
        # IDEMPOTENCE
        # --------------------------------------------------------

        if deposit.status == "paid":
            return deposit

        if (
            event_id
            and deposit.webhook_event_id == event_id
        ):
            return deposit

        expected_amount = self._money(
            deposit.amount
        )

        received_amount = self._money(
            amount
        )

        if received_amount != expected_amount:
            raise DepositServiceError(
                "Le montant du webhook ne correspond "
                "pas au dépôt."
            )

        deposit.commission_amount = (
            self._money(commission_amount)
            if commission_amount is not None
            else None
        )

        deposit.net_amount_credited = (
            self._money(net_amount_credited)
            if net_amount_credited is not None
            else expected_amount
        )

        if event_id:
            deposit.webhook_event_id = event_id

        deposit.webhook_received = True

        await self._credit_deposit(
            deposit
        )

        return deposit

    # ============================================================
    # CREDIT WALLET
    # ============================================================

    async def _credit_deposit(
        self,
        deposit: Deposit,
        provider_response: dict | None = None,
    ) -> None:

        # --------------------------------------------------------
        # IDEMPOTENCE
        # --------------------------------------------------------

        if deposit.status == "paid":
            return

        wallet = await self._get_wallet(
            deposit.user_id
        )

        amount_to_credit = (
            deposit.net_amount_credited
            or deposit.amount
        )

        amount_to_credit = self._money(
            amount_to_credit
        )

        if amount_to_credit <= 0:
            raise DepositServiceError(
                "Le montant à créditer est invalide."
            )

        # --------------------------------------------------------
        # OPERATION REFERENCE
        # --------------------------------------------------------

        operation_reference = (
            f"{deposit.reference}-CREDIT"
        )

        existing_operation = await self.db.execute(
            select(WalletOperation).where(
                WalletOperation.reference
                == operation_reference
            )
        )

        if existing_operation.scalar_one_or_none():
            deposit.status = "paid"
            deposit.paid_at = (
                deposit.paid_at
                or self._now()
            )

            await self.db.commit()
            return

        # --------------------------------------------------------
        # CREDIT WALLET
        # --------------------------------------------------------

        wallet.available_balance = (
            self._money(
                wallet.available_balance
            )
            + amount_to_credit
        )

        operation = WalletOperation(
            wallet_id=wallet.id,
            operation_type="deposit",
            amount=amount_to_credit,
            currency=deposit.currency,
            status="completed",
            provider_reference=(
                deposit.jessikapay_request_id
            ),
            reference=operation_reference,
            description=(
                f"Dépôt JessiKaPay confirmé "
                f"{deposit.reference}"
            ),
        )

        self.db.add(operation)

        # --------------------------------------------------------
        # UPDATE DEPOSIT
        # --------------------------------------------------------

        deposit.status = "paid"
        deposit.paid_at = self._now()

        await self.db.flush()

        deposit.wallet_operation_id = operation.id

        await self.db.commit()
        await self.db.refresh(deposit)

    # ============================================================
    # CANCEL
    # ============================================================

    async def cancel_deposit(
        self,
        *,
        deposit_id: int,
        user_id: int,
    ) -> Deposit:

        deposit = await self._get_deposit(
            deposit_id
        )

        if deposit.user_id != user_id:
            raise DepositServiceError(
                "Accès refusé."
            )

        if deposit.status not in (
            "pending",
            "reviewing",
            "awaiting_payment",
        ):
            raise DepositServiceError(
                "Ce dépôt ne peut plus être annulé."
            )

        deposit.status = "cancelled"
        deposit.cancelled_at = self._now()

        await self.db.commit()
        await self.db.refresh(deposit)

        return deposit

    # ============================================================
    # DATETIME PARSER
    # ============================================================

    @staticmethod
    def _parse_datetime(
        value,
    ) -> datetime | None:

        if not value:
            return None

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):

            normalized = value.replace(
                "Z",
                "+00:00",
            )

            try:
                return datetime.fromisoformat(
                    normalized
                )
            except ValueError:
                return None

        return None
