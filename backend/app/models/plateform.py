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

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Exemple : XAF, XOF, USD, EUR
    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )

    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    blocked_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    total_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    total_fees_collected: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

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

    ledger_entries = relationship(
        "PlatformLedger",
        back_populates="wallet",
        cascade="all, delete-orphan",
    )


class PlatformLedger(Base):
    __tablename__ = "platform_ledger"

    __table_args__ = (
        UniqueConstraint(
            "reference",
            name="uq_platform_ledger_reference",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("platform_wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    reference: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    operation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    wallet = relationship(
        "PlatformWallet",
        back_populates="ledger_entries",
    )

    transaction = relationship(
        "Transaction",
    )
