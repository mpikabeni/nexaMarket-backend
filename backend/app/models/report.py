from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Report(Base):
    __tablename__ = "reports"

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # TRANSACTION
    # ========================================================

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey(
            "transactions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # ========================================================
    # REPORTER
    # ========================================================

    reporter_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ========================================================
    # REPORT
    # ========================================================

    report_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
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

    # pending
    # investigating
    # resolved
    # rejected
    # cancelled

    # ========================================================
    # ADMIN
    # ========================================================

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

    admin_resolution: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )

    resolved_at: Mapped[datetime | None] = (
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

    transaction = relationship(
        "Transaction",
        foreign_keys=[transaction_id],
        back_populates="reports",
    )

    reporter = relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="reports",
    )

    assigned_admin = relationship(
        "User",
        foreign_keys=[assigned_admin_id],
        back_populates="assigned_reports",
    )
