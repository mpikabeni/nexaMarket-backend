from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    reference: Mapped[str] = mapped_column(
        String(120),
        unique=True,
        nullable=False,
        index=True,
    )

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

    assigned_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ========================================================
    # AMOUNTS
    # ========================================================

    channel_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    platform_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    provider_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    total_buyer_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    seller_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    platform_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        default=Decimal("0.050000"),
        nullable=False,
    )

    # ========================================================
    # TRANSACTION STATUS
    # ========================================================

    status: Mapped[str] = mapped_column(
        String(40),
        default="pending_payment",
        nullable=False,
        index=True,
    )

    # ========================================================
    # PAYMENT PROVIDER
    # ========================================================

    payment_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(150),
        unique=True,
        nullable=True,
        index=True,
    )

    # ID fourni par JessiKaPay lors de la création
    # du payment-request.
    jessikapay_request_id: Mapped[str | None] = mapped_column(
        String(150),
        unique=True,
        nullable=True,
        index=True,
    )

    payment_status: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # ========================================================
    # ESCROW
    # ========================================================

    escrow_held: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    escrow_held_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    protection_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # ========================================================
    # CHANNEL TRANSFER
    # ========================================================

    transfer_started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    transfer_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    buyer_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # ========================================================
    # DISPUTE
    # ========================================================

    dispute_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    disputed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    dispute_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # ========================================================
    # SELLER PAYOUT
    # ========================================================

    seller_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    seller_payout_reference: Mapped[str | None] = mapped_column(
        String(150),
        unique=True,
        nullable=True,
        index=True,
    )

    # ID de transaction retourné par JessiKaPay.
    jessikapay_payout_transaction_id: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        unique=True,
        nullable=True,
        index=True,
    )

    nexmarket_fee_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # ========================================================
    # REFUND / CANCELLATION
    # ========================================================

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    refund_reference: Mapped[str | None] = mapped_column(
        String(150),
        unique=True,
        nullable=True,
    )

    admin_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # TIMESTAMPS
    # ========================================================

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

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    listing = relationship(
        "Listing",
        back_populates="transactions",
    )

    buyer = relationship(
        "User",
        foreign_keys=[buyer_id],
        back_populates="buyer_transactions",
    )

    seller = relationship(
        "User",
        foreign_keys=[seller_id],
        back_populates="seller_transactions",
    )

    assigned_admin = relationship(
        "User",
        foreign_keys=[assigned_admin_id],
    )

    messages = relationship(
        "Message",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )

    reports = relationship(
        "Report",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )

    reviews = relationship(
        "Review",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
