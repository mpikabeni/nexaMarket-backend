from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Type de problème signalé
    report_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="other",
    )

    # Description fournie par l'utilisateur
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # pending / reviewing / resolved / rejected
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    # Admin responsable du traitement
    assigned_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Réponse/décision de l'administration
    admin_resolution: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    transaction = relationship(
        "Transaction",
        back_populates="reports",
    )

    reporter = relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="reports",
    )

    assigned_admin = relationship(
        "User",
        foreign_keys=[assigned_admin_id],
    )
