from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    # =========================================================
    # IDENTIFIANT INTERNE
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # TELEGRAM
    # =========================================================

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    first_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    last_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    photo_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # =========================================================
    # IDENTIFIANT NEXAMARKET
    # =========================================================

    nexa_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=True,
    )

    # =========================================================
    # COMPTE
    # =========================================================

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # =========================================================
    # PREFERENCES
    # =========================================================

    language: Mapped[str] = mapped_column(
        String(10),
        default="fr",
        nullable=False,
    )

    # Monnaie préférée de l'utilisateur pour l'affichage.
    #
    # IMPORTANT :
    # Cette valeur ne détermine PAS la monnaie d'une annonce.
    # Chaque Listing possède sa propre currency.
    preferred_currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
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

    wallet = relationship(
        "Wallet",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    listings = relationship(
        "Listing",
        back_populates="seller",
    )

    buyer_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.buyer_id",
        back_populates="buyer",
    )

    seller_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.seller_id",
        back_populates="seller",
    )

    messages = relationship(
        "Message",
        back_populates="sender",
    )

    channels = relationship(
        "Channel",
        back_populates="owner",
    )

    favorites = relationship(
        "Favorite",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    reviews = relationship(
        "Review",
        back_populates="user",
    )

    reports = relationship(
        "Report",
        back_populates="reporter",
    )
