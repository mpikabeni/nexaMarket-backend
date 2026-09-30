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


class Listing(Base):
    __tablename__ = "listings"

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # CHANNEL
    # ========================================================

    channel_id: Mapped[int] = mapped_column(
        ForeignKey(
            "channels.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ========================================================
    # SELLER
    # ========================================================

    seller_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ========================================================
    # PRICE
    # ========================================================

    price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="XAF",
    )

    # ========================================================
    # LISTING INFORMATION
    # ========================================================

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    # ========================================================
    # STATUS
    # ========================================================

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        index=True,
    )

    # draft
    # pending_review
    # approved
    # rejected
    # published
    # reserved
    # sold
    # suspended
    # cancelled

    # ========================================================
    # ADMIN REVIEW
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

    reviewed_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    rejection_reason: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )

    # ========================================================
    # NEXMARKET COMMISSION
    # ========================================================

    platform_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        nullable=False,
        default=Decimal("0.050000"),
    )

    # ========================================================
    # PUBLICATION
    # ========================================================

    is_public: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )

    published_at: Mapped[datetime | None] = (
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

    channel = relationship(
        "Channel",
        foreign_keys=[channel_id],
        back_populates="listings",
    )

    seller = relationship(
        "User",
        foreign_keys=[seller_id],
        back_populates="listings",
    )

    reviewed_by_admin = relationship(
        "User",
        foreign_keys=[reviewed_by_admin_id],
        back_populates="reviewed_listings",
    )

    transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.listing_id",
        back_populates="listing",
    )

    favorites = relationship(
        "Favorite",
        foreign_keys="Favorite.listing_id",
        back_populates="listing",
        cascade="all, delete-orphan",
    )
