from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Channel(Base):
    __tablename__ = "channels"

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # TELEGRAM CHANNEL
    # ========================================================

    telegram_channel_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
    )

    telegram_username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    photo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    subscriber_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # ========================================================
    # OWNER
    # ========================================================

    owner_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ID Telegram du propriétaire.
    #
    # Champ privé : ne doit jamais être exposé dans
    # les réponses publiques du marketplace.

    owner_telegram_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # ========================================================
    # BOT VERIFICATION
    # ========================================================

    bot_is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    bot_permissions_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    owner_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # ========================================================
    # VERIFICATION STATUS
    # ========================================================

    verification_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    # pending
    # submitted
    # approved
    # rejected
    # suspended

    # ========================================================
    # ADMIN VERIFICATION
    # ========================================================

    verified_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    verified_by_admin_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey(
                "users.id",
                ondelete="SET NULL",
            ),
            nullable=True,
            index=True,
        )
    )

    rejection_reason: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )

    # ========================================================
    # PUBLICATION
    # ========================================================

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    is_listed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
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

    owner = relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="channels",
    )

    verified_by_admin = relationship(
        "User",
        foreign_keys=[verified_by_admin_id],
        back_populates="verified_channels",
    )

    listings = relationship(
        "Listing",
        foreign_keys="Listing.channel_id",
        back_populates="channel",
        cascade="all, delete-orphan",
    )
