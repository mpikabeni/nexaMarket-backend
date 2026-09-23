# backend/app/models/platform.py

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlatformWallet(Base):
    """
    Portefeuille interne de NexMarket.

    Il est séparé des wallets des utilisateurs.
    Il reçoit notamment la commission NexMarket.
    """

    __tablename__ = "platform_wallet"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    # =========================================================
    # BALANCE
    # =========================================================

    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="XAF",
        nullable=False,
    )

    # =========================================================
    # TIMESTAMP
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformWallet "
            f"id={self.id} "
            f"balance={self.balance}>"
        )


class PlatformLedger(Base):
    """
    Journal financier de NexMarket.

    Chaque mouvement de la plateforme est enregistré ici :
    - commission sur une vente
    - frais éventuels
    - remboursement de commission
    - ajustement administratif
    """

    __tablename__ = "platform_ledger"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    # =========================================================
    # OPERATION
    # =========================================================

    operation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="XAF",
        nullable=False,
    )

    # Crédit ou débit
    direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # TRANSACTION ASSOCIATED
    # =========================================================

    transaction_id: Mapped[int | None] = mapped_column(
        nullable=True,
        index=True,
    )

    # =========================================================
    # TIMESTAMP
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformLedger "
            f"id={self.id} "
            f"reference={self.reference!r} "
            f"direction={self.direction!r} "
            f"amount={self.amount}>"
        )