from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformWallet(Base):
    __tablename__ = "platform_wallets"

    __table_args__ = (
        UniqueConstraint(
            "currency",
            name="uq_platform_wallet_currency",
        ),
    )

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # CURRENCY
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="XAF",
        index=True,
    )

    # ========================================================
    # BALANCES
    # ========================================================

    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    blocked_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    total_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    total_fees_collected: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    # ========================================================
    # TIMESTAMPS
    # ========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    ledger_entries = relationship(
        "PlatformLedger",
        foreign_keys="PlatformLedger.wallet_id",
        back_populates="wallet",
        cascade="all, delete-orphan",
    )


class PlatformLedger(Base):
    __tablename__ = "platform_ledger"

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # PLATFORM WALLET
    # ========================================================

    wallet_id: Mapped[int] = mapped_column(
        ForeignKey(
            "platform_wallets.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # ========================================================
    # TRANSACTION
    # ========================================================

    transaction_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey(
                "transactions.id",
                ondelete="SET NULL",
            ),
            nullable=True,
            index=True,
        )
    )

    # ========================================================
    # OPERATION
    # ========================================================

    reference: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        unique=True,
        index=True,
    )

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
        nullable=False,
        default="XAF",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # TIMESTAMP
    # ========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    wallet = relationship(
        "PlatformWallet",
        foreign_keys=[wallet_id],
        back_populates="ledger_entries",
    )

    transaction = relationship(
        "Transaction",
        foreign_keys=[transaction_id],
        back_populates="platform_ledger_entries",
    )
