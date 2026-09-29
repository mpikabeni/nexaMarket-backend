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


class Transaction(Base):
    __tablename__ = "transactions"

    # =========================================================
    # IDENTIFIANT
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Référence publique/interne NexMarket.
    # Elle doit être unique et générée côté backend.
    reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    # =========================================================
    # RELATIONS
    # =========================================================

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    buyer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    assigned_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # =========================================================
    # MONTANTS
    # =========================================================

    # Prix original de l'annonce.
    channel_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # Commission NexMarket.
    platform_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # Frais éventuels du fournisseur de paiement.
    provider_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # Montant total payé par l'acheteur.
    total_buyer_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # Montant destiné au vendeur après commission.
    seller_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    # =========================================================
    # MONNAIE
    # =========================================================

    # La monnaie est copiée depuis le Listing au moment
    # de la création de la transaction.
    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )

    # Taux réellement appliqué à cette transaction.
    # Il reste à 5 % même si la configuration change plus tard.
    platform_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        default=Decimal("0.050000"),
        nullable=False,
    )

    # =========================================================
    # ESCROW / STATUT
    # =========================================================

    status: Mapped[str] = mapped_column(
        String(40),
        default="pending_payment",
        nullable=False,
        index=True,
    )

    # Statuts prévus :
    #
    # pending_payment
    # payment_confirmed
    # waiting_admin
    # assigned
    # transfer_pending
    # protection_period
    # completed
    # cancelled
    # disputed
    # refunded

    # =========================================================
    # PAIEMENT
    # =========================================================

    payment_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    payment_status: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        index=True,
    )

    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # ESCROW
    # =========================================================

    escrow_held: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )

    escrow_held_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Date à partir de laquelle l'argent peut être libéré
    # si aucune contestation n'est ouverte.
    protection_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # TRANSFERT DU CANAL
    # =========================================================

    transfer_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    transfer_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    buyer_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    admin_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # LITIGE
    # =========================================================

    dispute_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    disputed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    dispute_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # =========================================================
    # REGLEMENT
    # =========================================================

    seller_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    nexmarket_fee_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Référence du règlement vendeur.
    seller_payout_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # =========================================================
    # ANNULATION / REMBOURSEMENT
    # =========================================================

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    refund_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # =========================================================
    # NOTES INTERNES
    # =========================================================

    admin_notes: Mapped[str | None] = mapped_column(
        Text,
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

    listing = relationship(
        "Listing",
        back_populates="transactions",
    )

    buyer = relationship(
        "User",
        foreign_keys=[buyer_id],
        back_populates="buyer_transactions",
    )

    seller = relationship(
        "User",
        foreign_keys=[seller_id],
        back_populates="seller_transactions",
    )

    assigned_admin = relationship(
        "User",
        foreign_keys=[assigned_admin_id],
    )

    messages = relationship(
        "Message",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )

    reports = relationship(
        "Report",
        back_populates="transaction",
    )
