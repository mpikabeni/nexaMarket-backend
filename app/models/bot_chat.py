from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BotChat(Base):
    """
    Canaux / groupes où le bot NexMarket a été ajouté (ou retiré).

    Alimentée par les événements Telegram `my_chat_member` : c'est ce qui
    permet aux statistiques du bot d'augmenter dès qu'on l'ajoute à un
    canal, avant même qu'il soit mis en vente dans l'application.
    """

    __tablename__ = "bot_chats"

    id: Mapped[int] = mapped_column(primary_key=True)

    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )

    chat_type: Mapped[str] = mapped_column(String(20), nullable=False)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # administrator | member | left | kicked | restricted
    bot_status: Mapped[str] = mapped_column(String(30), nullable=False)

    added_by_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
