# backend/app/models/transaction.py

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Transaction(Base):
    __tablename__ = "transactions"

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
    # LISTING / USERS
    # =========================================================

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    buyer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Administrateur qui prend en charge la transaction
    assigned_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # =========================================================
    # AMOUNTS
    # =========================================================

    # Prix accepté du canal
    channel_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # Commission NexMarket
    platform_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Frais du prestataire de paiement, s'ils existent
    provider_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Total payé par l'acheteur
    total_buyer_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # Montant final versé au vendeur
    seller_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="XAF",
        nullable=False,
    )

    # =========================================================
    # STATUS
    # =========================================================
    #
    # pending_payment
    # payment_confirmed
    # waiting_admin
    # assigned
    # transfer_pending
    # completed
    # cancelled
    # disputed
    # refunded
    #

    status: Mapped[str] = mapped_column(
        String(40),
        default="pending_payment",
        nullable=False,
        index=True,
    )

    # =========================================================
    # PAYMENT
    # =========================================================

    payment_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    payment_status: Mapped[str] = mapped_column(
        String(40),
        default="pending",
        nullable=False,
        index=True,
    )

    # =========================================================
    # TELEGRAM TRANSFER
    # =========================================================

    # Telegram chat ID du canal concerné
    telegram_chat_id: Mapped[int | None] = mapped_column(
        nullable=True,
        index=True,
    )

    transfer_started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    transfer_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # =========================================================
    # ADMIN / DISPUTE
    # =========================================================

    admin_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    dispute_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # TIMESTAMPS
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
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

    listing = relationship(
        "Listing",
        back_populates="transactions",
    )

    buyer = relationship(
        "User",
        foreign_keys=[buyer_id],
        back_populates="transactions_as_buyer",
    )

    seller = relationship(
        "User",
        foreign_keys=[seller_id],
        back_populates="transactions_as_seller",
    )

    assigned_admin = relationship(
        "User",
        foreign_keys=[assigned_admin_id],
    )

    messages = relationship(
        "Message",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction "
            f"id={self.id} "
            f"reference={self.reference!r} "
            f"status={self.status!r}>"
        )