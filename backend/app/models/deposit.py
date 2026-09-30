from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Deposit(Base):
    __tablename__ = "deposits"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_deposit_amount_positive",
        ),
        Index(
            "ix_deposits_user_status",
            "user_id",
            "status",
        ),
        Index(
            "ix_deposits_jessikapay_request_id",
            "jessikapay_request_id",
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
    # USER
    # ========================================================

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
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
    # AMOUNT
    # ========================================================

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="XAF",
    )

    # ========================================================
    # USER DEPOSIT INFORMATION
    # ========================================================

    country: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    phone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # ========================================================
    # JESSIKAPAY
    # ========================================================

    jessikapay_request_id: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        unique=True,
        index=True,
    )

    jessikapay_code: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    payment_link: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # PROVIDER AMOUNTS
    # ========================================================

    commission_amount: Mapped[Decimal | None] = (
        mapped_column(
            Numeric(18, 2),
            nullable=True,
        )
    )

    net_amount_credited: Mapped[Decimal | None] = (
        mapped_column(
            Numeric(18, 2),
            nullable=True,
        )
    )

    # ========================================================
    # STATUS
    # ========================================================

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    # Valeurs prévues :
    #
    # pending
    # reviewing
    # awaiting_payment
    # paid
    # failed
    # expired
    # cancelled

    # ========================================================
    # WEBHOOK / IDEMPOTENCY
    # ========================================================

    webhook_received: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )

    webhook_event_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        unique=True,
    )

    # ========================================================
    # WALLET OPERATION
    # ========================================================

    wallet_operation_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey(
                "wallet_operations.id",
                ondelete="SET NULL",
            ),
            nullable=True,
            unique=True,
        )
    )

    # ========================================================
    # FAILURE
    # ========================================================

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # DATES
    # ========================================================

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="deposits",
    )

    wallet_operation = relationship(
        "WalletOperation",
        foreign_keys=[wallet_operation_id],
    )
