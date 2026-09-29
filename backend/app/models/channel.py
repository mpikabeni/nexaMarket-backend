from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

    # =========================================================
    # IDENTIFIANT
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # TELEGRAM CHANNEL
    # =========================================================

    telegram_channel_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
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
        String(1000),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    subscriber_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # =========================================================
    # PROPRIETAIRE NEXAMARKET
    # =========================================================

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ID Telegram du propriétaire vérifié.
    #
    # Ce champ reste strictement interne.
    # Il ne doit jamais être envoyé dans une annonce publique.
    owner_telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    # =========================================================
    # VERIFICATION TELEGRAM
    # =========================================================

    # Le bot NexMarket est-il administrateur ?
    bot_is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Le bot possède-t-il les droits nécessaires ?
    bot_permissions_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Le vendeur est-il réellement creator/propriétaire ?
    owner_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # =========================================================
    # VERIFICATION NEXAMARKET
    # =========================================================

    verification_status: Mapped[str] = mapped_column(
        String(40),
        default="pending",
        nullable=False,
        index=True,
    )

    # pending
    # submitted
    # approved
    # rejected
    # suspended

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    verified_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # ETAT DU CANAL
    # =========================================================

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    is_listed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
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

    owner = relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="channels",
    )

    verified_by_admin = relationship(
        "User",
        foreign_keys=[verified_by_admin_id],
    )

    listings = relationship(
        "Listing",
        back_populates="channel",
    )
