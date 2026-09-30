from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="XAF", nullable=False)
    jessikapay_jp_number: Mapped[str] = mapped_column(String(255), nullable=False)
    jessikapay_transaction_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    admin_note: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    user = relationship("User", foreign_keys=[user_id])
    reviewed_by_admin = relationship("User", foreign_keys=[reviewed_by_admin_id])
