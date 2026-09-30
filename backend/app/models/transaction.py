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

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # INTERNAL REFERENCE
    # ========================================================

    reference: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    # ========================================================
    # LISTING
    # ========================================================

    listing_id: Mapped[int] = mapped_column(
        ForeignKey(
            "listings.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ========================================================
    # PARTICIPANTS
    # ========================================================

    buyer_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    assigned_admin_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey(
                "users.id",
                ondelete="SET NULL",
            ),
            nullable=True,
            index=True,
        )
    )

    # ========================================================
    # FINANCIAL VALUES
    # ========================================================

    channel_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    platform_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    provider_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
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
        default="XAF",
    )

    platform_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        nullable=False,
        default=Decimal("0.050000"),
    )

    # ========================================================
    # TRANSACTION STATUS
    # ========================================================

    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending_payment",
        index=True,
    )

    # pending_payment
    # payment_confirmed
    # waiting_admin
    # transfer_started
    # protection_period
    # completed
    # disputed
    # cancelled
    # refunded

    # ========================================================
    # PAYMENT PROVIDER
    # ========================================================

    payment_provider: Mapped[str | None] = (
        mapped_column(
            String(50),
            nullable=True,
        )
    )

    payment_reference: Mapped[str | None] = (
        mapped_column(
            String(150),
            nullable=True,
            unique=True,
            index=True,
        )
    )

    jessikapay_request_id: Mapped[str | None] = (
        mapped_column(
            String(150),
            nullable=True,
            unique=True,
            index=True,
        )
    )

    payment_status: Mapped[str | None] = (
        mapped_column(
            String(40),
            nullable=True,
            index=True,
        )
    )

    payment_confirmed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    # ========================================================
    # ESCROW
    # ========================================================

    escrow_held: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    escrow_held_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    # ========================================================
    # CHANNEL TRANSFER
    # ========================================================

    transfer_started_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    transfer_completed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    protection_ends_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    # ========================================================
    # BUYER CONFIRMATION
    # ========================================================

    buyer_confirmed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    # ========================================================
    # DISPUTE
    # ========================================================

    dispute_reason: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )

    disputed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    dispute_resolved_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    # ========================================================
    # SELLER PAYOUT
    # ========================================================

    seller_paid_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    seller_payout_reference: Mapped[str | None] = (
        mapped_column(
            String(150),
            nullable=True,
            unique=True,
            index=True,
        )
    )

    jessikapay_payout_transaction_id: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
        unique=True,
        index=True,
    )

    # ========================================================
    # NEXMARKET COMMISSION
    # ========================================================

    nexmarket_fee_recorded_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # CANCELLATION / REFUND
    # ========================================================

    cancelled_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    refunded_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    refund_reference: Mapped[str | None] = (
        mapped_column(
            String(150),
            nullable=True,
        )
    )

    # ========================================================
    # ADMIN NOTES
    # ========================================================

    admin_notes: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
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

    listing = relationship(
        "Listing",
        foreign_keys=[listing_id],
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
        back_populates="assigned_transactions",
    )

    messages = relationship(
        "Message",
        foreign_keys="Message.transaction_id",
        back_populates="transaction",
    )

    reports = relationship(
        "Report",
        foreign_keys="Report.transaction_id",
        back_populates="transaction",
    )

    reviews = relationship(
        "Review",
        foreign_keys="Review.transaction_id",
        back_populates="transaction",
    )
