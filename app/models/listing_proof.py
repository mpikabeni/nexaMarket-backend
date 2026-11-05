from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ListingProof(Base):
    """
    Photo de preuve fournie par le vendeur (capture des statistiques,
    preuve de propriété...). Conservée en base : l'administrateur peut
    la consulter à tout moment depuis la console, même si le message
    Telegram a été supprimé.
    """

    __tablename__ = "listing_proofs"

    id: Mapped[int] = mapped_column(primary_key=True)

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(50),
        default="image/jpeg",
        nullable=False,
    )

    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
