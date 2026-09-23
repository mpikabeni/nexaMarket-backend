from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# AUTH
# ============================================================

class TelegramLoginRequest(BaseModel):
    init_data: str


class TelegramLoginResponse(BaseModel):
    user: dict[str, Any]
    token: str | None = None


# ============================================================
# USERS
# ============================================================

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int
    nexa_id: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    photo_url: str | None = None
    is_active: bool
    is_admin: bool
    language: str
    currency: str
    created_at: datetime
    updated_at: datetime


class UserLanguageUpdate(BaseModel):
    language: Literal["fr", "en"]


class UserCurrencyUpdate(BaseModel):
    currency: Literal["XAF"]


# ============================================================
# WALLET
# ============================================================

class DepositRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    phone: str = Field(min_length=5, max_length=30)
    customer_name: str | None = Field(default=None, max_length=150)


class DepositResponse(BaseModel):
    status: str
    token: str | None = None
    payment_url: str | None = None
    amount: Decimal | None = None
    message: str | None = None


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    phone: str = Field(min_length=5, max_length=30)
    withdraw_mode: str | None = None


class WithdrawResponse(BaseModel):
    status: str
    reference: str | None = None
    message: str | None = None


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    available_balance: Decimal
    blocked_balance: Decimal
    total_revenue: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime


class WalletOperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wallet_id: int
    operation_type: str
    amount: Decimal
    currency: str
    status: str
    provider_reference: str | None = None
    reference: str | None = None
    description: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


# ============================================================
# CHANNELS
# ============================================================

class ChannelCreateRequest(BaseModel):
    username: str
    category: str
    country: str
    language: str = "fr"


class ChannelUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    username: str | None = None
    category: str | None = None
    country: str | None = None
    language: str | None = None


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_chat_id: int
    title: str
    username: str | None = None
    description: str | None = None
    photo_url: str | None = None
    category: str | None = None
    country: str | None = None
    language: str | None = None
    subscribers_count: int
    telegram_verified: bool
    bot_is_admin: bool
    seller_is_admin: bool
    verification_note: str | None = None
    verified_at: datetime | None = None
    owner_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ============================================================
# LISTINGS
# ============================================================

class ListingCreate(BaseModel):
    channel_id: int
    price: Decimal = Field(gt=0)
    currency: str = "XAF"
    description: str | None = Field(default=None, max_length=5000)


class ListingUpdate(BaseModel):
    price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    description: str | None = Field(default=None, max_length=5000)


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    seller_id: int
    price: Decimal
    currency: str
    description: str | None = None
    status: str
    admin_note: str | None = None
    validated_by_id: int | None = None
    validated_at: datetime | None = None
    locked_price: Decimal | None = None
    locked_at: datetime | None = None
    publish_fee: Decimal
    publish_fee_paid: bool
    created_at: datetime
    updated_at: datetime


# ============================================================
# TRANSACTIONS
# ============================================================

class TransactionCreate(BaseModel):
    listing_id: int


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: str
    listing_id: int
    buyer_id: int
    seller_id: int
    assigned_admin_id: int | None = None

    channel_price: Decimal
    platform_fee: Decimal
    provider_fee: Decimal
    total_buyer_amount: Decimal
    seller_amount: Decimal
    currency: str

    status: str

    payment_provider: str | None = None
    payment_reference: str | None = None
    payment_status: str | None = None

    telegram_chat_id: int | None = None

    transfer_started_at: datetime | None = None
    transfer_completed_at: datetime | None = None

    admin_note: str | None = None
    cancellation_reason: str | None = None
    dispute_reason: str | None = None

    created_at: datetime
    updated_at: datetime


class AdminTransactionAction(BaseModel):
    action: Literal[
        "assign",
        "start_transfer",
        "complete",
        "cancel",
        "dispute",
    ]
    note: str | None = Field(default=None, max_length=5000)


# ============================================================
# MESSAGES
# ============================================================

class MessageCreate(BaseModel):
    transaction_id: int
    content: str | None = Field(default=None, max_length=10000)
    message_type: Literal[
        "text",
        "image",
        "document",
        "system",
    ] = "text"
    media_url: str | None = None
    media_type: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    sender_id: int
    content: str | None = None
    message_type: str
    media_url: str | None = None
    media_type: str | None = None
    is_system_message: bool
    is_read: bool
    created_at: datetime


# ============================================================
# FAVORITES
# ============================================================

class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    listing_id: int
    created_at: datetime


# ============================================================
# REVIEWS
# ============================================================

class ReviewCreate(BaseModel):
    transaction_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=3000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    reviewer_id: int
    reviewed_user_id: int
    rating: int
    comment: str | None = None
    is_visible: bool
    created_at: datetime
    updated_at: datetime


# ============================================================
# REPORTS
# ============================================================

class ReportCreate(BaseModel):
    listing_id: int | None = None
    transaction_id: int | None = None
    reason: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporter_id: int
    listing_id: int | None = None
    transaction_id: int | None = None
    reason: str
    description: str | None = None
    status: str
    admin_note: str | None = None
    resolved_by_id: int | None = None
    created_at: datetime
    resolved_at: datetime | None = None


# ============================================================
# ADMIN
# ============================================================

class AdminLoginRequest(BaseModel):
    code: str


class AdminLoginResponse(BaseModel):
    token: str
    expires_in: int


class AdminListingDecision(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=5000)


# ============================================================
# PAGINATION
# ============================================================

class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class MessageResponseSimple(BaseModel):
    success: bool
    message: str
