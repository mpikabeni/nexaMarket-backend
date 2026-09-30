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


class Message(Base):
    __tablename__ = "messages"

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
    # SENDER
    # ========================================================

    sender_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # ID Telegram conservé pour les besoins internes.
    # Ne jamais l'exposer dans l'API publique.

    sender_telegram_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # ========================================================
    # ROLE
    # ========================================================

    sender_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    # buyer
    # seller
    # admin

    # ========================================================
    # CONTENT
    # ========================================================

    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    message_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="text",
    )

    # text
    # image
    # document
    # system

    attachment_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    attachment_file_id: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # ========================================================
    # SYSTEM MESSAGE
    # ========================================================

    is_system_message: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # ========================================================
    # READ STATUS
    # ========================================================

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by_admin_id: Mapped[int | None] = (
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
    # TIMESTAMPS
    # ========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
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
