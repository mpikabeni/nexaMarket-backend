# backend/app/models/listing.py

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Listing(Base):
    __tablename__ = "listings"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # SALE INFORMATION
    # =========================================================

    price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="XAF",
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # STATUS
    # =========================================================
    #
    # pending   = en attente de validation admin
    # available = publié et disponible
    # reserved  = prix/fonds bloqués pour une transaction
    # sold      = vendu
    # rejected  = refusé par l'administration
    # cancelled = annonce annulée
    # archived  = ancienne annonce
    #

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        nullable=False,
        index=True,
    )

    # =========================================================
    # MODERATION
    # =========================================================

    admin_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    validated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # =========================================================
    # PRICE LOCK
    # =========================================================

    # Lorsque l'annonce est utilisée dans une transaction,
    # le prix accepté doit rester verrouillé.

    locked_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # =========================================================
    # PUBLISHING FEE
    # =========================================================

    publish_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    publish_fee_paid: Mapped[bool] = mapped_column(
        default=False,
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

    channel = relationship(
        "Channel",
        back_populates="listings",
    )

    seller = relationship(
        "User",
        foreign_keys=[seller_id],
    )

    validated_by = relationship(
        "User",
        foreign_keys=[validated_by_id],
    )

    transactions = relationship(
        "Transaction",
        back_populates="listing",
    )

    favorites = relationship(
        "Favorite",
        back_populates="listing",
        cascade="all, delete-orphan",
    )

    reports = relationship(
        "Report",
        back_populates="listing",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Listing id={self.id} "
            f"channel_id={self.channel_id} "
            f"seller_id={self.seller_id} "
            f"price={self.price} "
            f"status={self.status!r}>"
        )
