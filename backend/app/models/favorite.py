# backend/app/models/favorite.py

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Favorite(Base):
    __tablename__ = "favorites"

    # =========================================================
    # IDENTIFICATION
    # =========================================================

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # TIMESTAMP
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # =========================================================
    # CONTRAINTE
    # =========================================================
    #
    # Un utilisateur ne peut ajouter deux fois
    # la même annonce à ses favoris.
    #

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "listing_id",
            name="uq_user_listing_favorite",
        ),
    )

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    user = relationship(
        "User",
        back_populates="favorites",
    )

    listing = relationship(
        "Listing",
        back_populates="favorites",
    )

    def __repr__(self) -> str:
        return (
            f"<Favorite "
            f"id={self.id} "
            f"user_id={self.user_id} "
            f"listing_id={self.listing_id}>"
        )