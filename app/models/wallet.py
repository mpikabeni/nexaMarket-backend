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


class Wallet(Base):
    __tablename__ = "wallets"

    # =========================================================
    # IDENTIFIANT
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # PROPRIETAIRE
    # =========================================================

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # =========================================================
    # SOLDES
    # =========================================================

    # Argent réellement disponible pour l'utilisateur.
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Argent actuellement bloqué dans une transaction/escrow.
    blocked_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Revenus cumulés du vendeur.
    total_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # =========================================================
    # MONNAIE
    # =========================================================

    # Cette monnaie concerne le portefeuille.
    # Elle ne définit PAS la monnaie d'une annonce.
    currency: Mapped[str] = mapped_column(
        String(10),
        default="XAF",
        nullable=False,
    )

    # =========================================================
    # DATES
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # =========================================================
    # RELATIONS
    # =========================================================

    user = relationship(
        "User",
        back_populates="wallet",
    )

    operations = relationship(
        "WalletOperation",
        back_populates="wallet",
        cascade="all, delete-orphan",
    )


class WalletOperation(Base):
    __tablename__ = "wallet_operations"

    # =========================================================
    # IDENTIFIANT
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # WALLET
    # =========================================================

    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"),
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
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    # =========================================================
    # REFERENCES
    # =========================================================

    # Référence du fournisseur de paiement.
    provider_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # Référence interne NexMarket.
    # Elle doit être unique pour empêcher les doublons.
    reference: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    # Description destinée à l'historique interne.
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # DATES
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # =========================================================
    # RELATION
    # =========================================================

    wallet = relationship(
        "Wallet",
        back_populates="operations",
    )

    # =========================================================
    # CONTRAINTES
    # =========================================================

    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "reference",
            name="uq_wallet_operation_reference",
        ),
    )
