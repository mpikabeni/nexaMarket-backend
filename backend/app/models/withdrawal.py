from datetime import datetime

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


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_withdrawal_amount_positive",
        ),
        Index(
            "ix_withdrawals_user_status",
            "user_id",
            "status",
        ),
        Index(
            "ix_withdrawals_provider_transaction_id",
            "jessikapay_transaction_id",
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
    # WITHDRAWAL REFERENCE
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

    amount: Mapped[float] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="XAF",
    )

    # ========================================================
    # JESSIKAPAY
    # ========================================================

    # Numéro JP utilisé pour le retrait.
    #
    # IMPORTANT :
    # Ce champ est privé et ne doit jamais être exposé
    # dans les réponses publiques.
    jessikapay_jp_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    jessikapay_transaction_id: Mapped[str | None] = (
        mapped_column(
            String(150),
            nullable=True,
            unique=True,
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
    # processing
    # payout_sent
    # completed
    # failed
    # rejected
    # cancelled

    # ========================================================
    # ADMIN
    # ========================================================

    reviewed_by_admin_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey(
                "users.id",
                ondelete="SET NULL",
            ),
            nullable=True,
            index=True,
        )
    )

    admin_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # FAILURE / REJECTION
    # ========================================================

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # DATES
    # ========================================================

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    processed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    completed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    rejected_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    cancelled_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
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

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="withdrawals",
    )

    reviewed_by_admin = relationship(
        "User",
        foreign_keys=[reviewed_by_admin_id],
    )
