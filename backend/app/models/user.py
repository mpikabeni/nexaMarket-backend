from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        index=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    first_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    last_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    photo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # ========================================================
    # NEXA ID
    # ========================================================

    nexa_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    # ========================================================
    # ACCOUNT
    # ========================================================

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # ========================================================
    # PREFERENCES
    # ========================================================

    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="fr",
    )

    preferred_currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="XAF",
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
    # WALLET
    # ========================================================

    wallet = relationship(
        "Wallet",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # ========================================================
    # LISTINGS
    # ========================================================

    listings = relationship(
        "Listing",
        foreign_keys="Listing.seller_id",
        back_populates="seller",
    )

    # ========================================================
    # TRANSACTIONS - BUYER
    # ========================================================

    buyer_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.buyer_id",
        back_populates="buyer",
    )

    # ========================================================
    # TRANSACTIONS - SELLER
    # ========================================================

    seller_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.seller_id",
        back_populates="seller",
    )

    # ========================================================
    # TRANSACTIONS - ADMIN
    # ========================================================

    assigned_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.assigned_admin_id",
        back_populates="assigned_admin",
    )

    # ========================================================
    # CHANNELS
    # ========================================================

    channels = relationship(
        "Channel",
        foreign_keys="Channel.owner_id",
        back_populates="owner",
    )

    # ========================================================
    # MESSAGES
    # ========================================================

    messages = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
    )

    # ========================================================
    # FAVORITES
    # ========================================================

    favorites = relationship(
        "Favorite",
        foreign_keys="Favorite.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # ========================================================
    # REVIEWS GIVEN
    # ========================================================

    reviews_given = relationship(
        "Review",
        foreign_keys="Review.reviewer_id",
        back_populates="reviewer",
        cascade="all, delete-orphan",
    )

    # ========================================================
    # REVIEWS RECEIVED
    # ========================================================

    reviews_received = relationship(
        "Review",
        foreign_keys="Review.reviewed_user_id",
        back_populates="reviewed_user",
    )

    # ========================================================
    # REPORTS
    # ========================================================

    reports = relationship(
        "Report",
        foreign_keys="Report.reporter_id",
        back_populates="reporter",
        cascade="all, delete-orphan",
    )

    # ========================================================
    # ADMIN REPORTS
    # ========================================================

    assigned_reports = relationship(
        "Report",
        foreign_keys="Report.assigned_admin_id",
        back_populates="assigned_admin",
    )

    # ========================================================
    # ADMIN REVIEW MODERATION
    # ========================================================

    moderated_reviews = relationship(
        "Review",
        foreign_keys="Review.moderated_by_admin_id",
        back_populates="moderated_by_admin",
    )

    # ========================================================
    # ADMIN CHANNEL VERIFICATION
    # ========================================================

    verified_channels = relationship(
        "Channel",
        foreign_keys="Channel.verified_by_admin_id",
        back_populates="verified_by_admin",
    )

    # ========================================================
    # ADMIN LISTING REVIEW
    # ========================================================

    reviewed_listings = relationship(
        "Listing",
        foreign_keys="Listing.reviewed_by_admin_id",
        back_populates="reviewed_by_admin",
    )

    # ========================================================
    # WITHDRAWALS
    # ========================================================

    withdrawals = relationship(
        "Withdrawal",
        foreign_keys="Withdrawal.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # ========================================================
    # DEPOSITS
    # ========================================================

    deposits = relationship(
        "Deposit",
        foreign_keys="Deposit.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # ========================================================
    # ADMIN WITHDRAWAL REVIEW
    # ========================================================

    reviewed_withdrawals = relationship(
        "Withdrawal",
        foreign_keys="Withdrawal.reviewed_by_admin_id",
        cascade="all",
    )
