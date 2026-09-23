# backend/app/models/wallet.py

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Wallet(Base):
    __tablename__ = "wallets"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # =========================================================
    # BALANCES
    # =========================================================

    # Argent réellement disponible
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Argent temporairement bloqué pendant une transaction
    blocked_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Revenus cumulés du vendeur
    total_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # =========================================================
    # CURRENCY
    # =========================================================

    currency: Mapped[str] = mapped_column(
        String(10),
        default="XAF",
        nullable=False,
    )

    # =========================================================
    # TIMESTAMPS
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

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    user = relationship(
        "User",
        back_populates="wallet",
    )

    operations = relationship(
        "WalletOperation",
        back_populates="wallet",
        cascade="all, delete-orphan",
        order_by="WalletOperation.created_at.desc()",
    )

    def __repr__(self) -> str:
        return (
            f"<Wallet id={self.id} "
            f"user_id={self.user_id} "
            f"available={self.available_balance} "
            f"blocked={self.blocked_balance}>"
        )


class WalletOperation(Base):
    __tablename__ = "wallet_operations"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # OPERATION
    # =========================================================
    #
    # deposit
    # withdrawal
    # transaction_hold
    # transaction_release
    # sale_revenue
    # platform_fee
    # refund
    # adjustment
    #

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

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        nullable=False,
        index=True,
    )

    # Identifiant fourni par le prestataire de paiement
    provider_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # Référence interne NexMarket
    reference: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # =========================================================
    # TIMESTAMP
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # =========================================================
    # RELATIONSHIP
    # =========================================================

    wallet = relationship(
        "Wallet",
        back_populates="operations",
    )

    def __repr__(self) -> str:
        return (
            f"<WalletOperation id={self.id} "
            f"type={self.operation_type!r} "
            f"amount={self.amount} "
            f"status={self.status!r}>"
        )