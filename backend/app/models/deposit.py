from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

class Deposit(Base):
    __tablename__ = "deposits"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="XAF", nullable=False)
    country: Mapped[str] = mapped_column(String(10), default="CG", nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    jessikapay_request_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    jessikapay_code: Mapped[str | None] = mapped_column(String(255))
    payment_link: Mapped[str | None] = mapped_column(Text)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(18,2))
    net_amount_credited: Mapped[Decimal | None] = mapped_column(Numeric(18,2))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    webhook_received: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    webhook_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    wallet_operation_id: Mapped[int | None] = mapped_column(ForeignKey("wallet_operations.id", ondelete="SET NULL"), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    user = relationship("User")
    wallet_operation = relationship("WalletOperation")
