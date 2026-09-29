from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Listing(Base):
    __tablename__ = "listings"

    # =========================================================
    # IDENTIFIANT
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # CANAL
    # =========================================================

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # VENDEUR
    # =========================================================

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # PRIX
    # =========================================================

    price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # La monnaie est choisie par le vendeur pour CETTE annonce.
    #
    # Exemple :
    #   50000 XAF
    #   100 USD
    #   70000 XOF
    #
    # Elle n'est pas déterminée par le profil utilisateur.
    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )

    # =========================================================
    # CONTENU PUBLIC
    # =========================================================

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    # =========================================================
    # STATUT DE L'ANNONCE
    # =========================================================

    status: Mapped[str] = mapped_column(
        String(40),
        default="draft",
        nullable=False,
        index=True,
    )

    # draft
    # pending_review
    # approved
    # rejected
    # published
    # reserved
    # sold
    # suspended
    # cancelled

    # =========================================================
    # MODERATION
    # =========================================================

    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # =========================================================
    # COMMISSION
    # =========================================================

    # Taux utilisé au moment de la vente.
    #
    # On le conserve dans la transaction finale également afin
    # qu'une modification future de la commission ne change
    # pas rétroactivement les anciennes ventes.
    platform_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        default=Decimal("0.050000"),
        nullable=False,
    )

    # =========================================================
    # VISIBILITE
    # =========================================================

    is_public: Mapped[bool] = mapped_column(
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

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # RELATIONS
    # =========================================================

    channel = relationship(
        "Channel",
        back_populates="listings",
    )

    seller = relationship(
        "User",
        foreign_keys=[seller_id],
        back_populates="listings",
    )

    reviewed_by_admin = relationship(
        "User",
        foreign_keys=[reviewed_by_admin_id],
    )

    transactions = relationship(
        "Transaction",
        back_populates="listing",
    )
