# backend/app/models/message.py

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Message(Base):
    __tablename__ = "messages"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # MESSAGE
    # =========================================================

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # text / image / document / system
    message_type: Mapped[str] = mapped_column(
        String(30),
        default="text",
        nullable=False,
    )

    # =========================================================
    # MEDIA
    # =========================================================

    media_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    media_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # =========================================================
    # SYSTEM MESSAGE
    # =========================================================

    is_system_message: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # =========================================================
    # READ STATUS
    # =========================================================

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # =========================================================
    # TIMESTAMP
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    transaction = relationship(
        "Transaction",
        back_populates="messages",
    )

    sender = relationship(
        "User",
        back_populates="messages",
    )

    def __repr__(self) -> str:
        return (
            f"<Message "
            f"id={self.id} "
            f"transaction_id={self.transaction_id} "
            f"sender_id={self.sender_id}>"
        )