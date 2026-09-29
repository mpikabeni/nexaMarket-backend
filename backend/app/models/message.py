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


class Message(Base):
    __tablename__ = "messages"

    # =========================================================
    # IDENTIFIANT
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # TRANSACTION
    # =========================================================

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # EXPEDITEUR
    # =========================================================

    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ID Telegram conservé pour l'audit.
    # Il reste une donnée interne.
    sender_telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    # =========================================================
    # ROLE AU MOMENT DU MESSAGE
    # =========================================================

    sender_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    # buyer
    # seller
    # admin

    # =========================================================
    # CONTENU
    # =========================================================

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # =========================================================
    # TYPE
    # =========================================================

    message_type: Mapped[str] = mapped_column(
        String(30),
        default="text",
        nullable=False,
    )

    # text
    # image
    # document
    # system

    # =========================================================
    # PIECE JOINTE
    # =========================================================

    attachment_url: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )

    attachment_file_id: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # =========================================================
    # MESSAGE SYSTEME
    # =========================================================

    is_system_message: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # =========================================================
    # LECTURE
    # =========================================================

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # MODERATION / AUDIT
    # =========================================================

    # Un message financier ou important ne doit pas pouvoir
    # disparaître silencieusement.
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # =========================================================
    # DATES
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
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

    transaction = relationship(
        "Transaction",
        back_populates="messages",
    )

    sender = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="messages",
    )

    deleted_by_admin = relationship(
        "User",
        foreign_keys=[deleted_by_admin_id],
    )
