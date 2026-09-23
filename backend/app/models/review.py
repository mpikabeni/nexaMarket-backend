# backend/app/models/review.py

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Review(Base):
    __tablename__ = "reviews"

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

    # Utilisateur qui laisse l'avis
    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Utilisateur évalué
    reviewed_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # REVIEW
    # =========================================================

    rating: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # MODERATION
    # =========================================================

    is_visible: Mapped[bool] = mapped_column(
        default=True,
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

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # =========================================================
    # CONSTRAINTS
    # =========================================================

    __table_args__ = (
        # Une seule évaluation par utilisateur et transaction.
        UniqueConstraint(
            "transaction_id",
            "reviewer_id",
            name="uq_review_transaction_reviewer",
        ),

        # Note comprise entre 1 et 5.
        CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_review_rating_range",
        ),
    )

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    transaction = relationship(
        "Transaction",
    )

    reviewer = relationship(
        "User",
        foreign_keys=[reviewer_id],
        back_populates="reviews_written",
    )

    reviewed_user = relationship(
        "User",
        foreign_keys=[reviewed_user_id],
    )

    def __repr__(self) -> str:
        return (
            f"<Review "
            f"id={self.id} "
            f"transaction_id={self.transaction_id} "
            f"rating={self.rating}>"
        )