# backend/app/schemas.py

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# =========================================================
# BASE
# =========================================================

class APIBaseModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


# =========================================================
# AUTH
# =========================================================

class TelegramAuthRequest(BaseModel):
    init_data: str = Field(
        ...,
        min_length=1,
        description="Telegram WebApp initData",
    )


class UserResponse(APIBaseModel):
    id: int
    telegram_id: int
    nexa_id: str

    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    photo_url: str | None = None

    language: str
    currency: str

    is_active: bool
    is_admin: bool

    created_at: datetime


class AuthResponse(BaseModel):
    user: UserResponse
    is_new_user: bool


# =========================================================
# WALLET
# =========================================================

class WalletResponse(APIBaseModel):
    id: int
    user_id: int

    available_balance: Decimal
    blocked_balance: Decimal
    total_revenue: Decimal

    currency: str

    created_at: datetime
    updated_at: datetime


class WalletOperationResponse(APIBaseModel):
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


class DepositRequest(BaseModel):
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Montant du dépôt",
    )

    currency: str = Field(
        default="XAF",
        min_length=3,
        max_length=10,
    )

    country: str | None = Field(
        default=None,
        max_length=100,
    )

    phone_number: str | None = Field(
        default=None,
        max_length=50,
    )


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(
        ...,
        gt=0,
    )

    currency: str = Field(
        default="XAF",
        min_length=3,
        max_length=10,
    )

    country: str | None = Field(
        default=None,
        max_length=100,
    )

    phone_number: str = Field(
        ...,
        min_length=5,
        max_length=50,
    )


class PaymentCheckoutResponse(BaseModel):
    status: str
    reference: str

    checkout_url: str | None = None

    amount: Decimal
    currency: str


# =========================================================
# CHANNEL
# =========================================================

class ChannelCreate(BaseModel):
    username: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    price: Decimal = Field(
        ...,
        gt=0,
    )

    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    country: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    language: str = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )


class ChannelUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=2,
        max_length=255,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )

    category: str | None = Field(
        default=None,
        max_length=100,
    )

    country: str | None = Field(
        default=None,
        max_length=100,
    )

    language: str | None = Field(
        default=None,
        max_length=50,
    )

    price: Decimal | None = Field(
        default=None,
        gt=0,
    )


class ChannelResponse(APIBaseModel):
    id: int

    telegram_chat_id: int | None = None

    title: str
    username: str | None = None
    description: str | None = None
    photo_url: str | None = None

    category: str
    country: str
    language: str

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


# =========================================================
# LISTING
# =========================================================

class ListingCreate(ChannelCreate):
    pass


class ListingUpdate(BaseModel):
    price: Decimal | None = Field(
        default=None,
        gt=0,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )

    category: str | None = Field(
        default=None,
        max_length=100,
    )

    country: str | None = Field(
        default=None,
        max_length=100,
    )

    language: str | None = Field(
        default=None,
        max_length=50,
    )


class ListingResponse(APIBaseModel):
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

    channel: ChannelResponse | None = None


# =========================================================
# TRANSACTION
# =========================================================

class TransactionCreate(BaseModel):
    listing_id: int


class TransactionResponse(APIBaseModel):
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
    payment_status: str

    telegram_chat_id: int | None = None

    transfer_started_at: datetime | None = None
    transfer_completed_at: datetime | None = None

    admin_note: str | None = None
    cancellation_reason: str | None = None
    dispute_reason: str | None = None

    created_at: datetime
    payment_confirmed_at: datetime | None = None
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    updated_at: datetime


class TransactionStatusUpdate(BaseModel):
    status: str = Field(
        ...,
        min_length=1,
        max_length=40,
    )

    note: str | None = Field(
        default=None,
        max_length=5000,
    )


# =========================================================
# MESSAGES
# =========================================================

class MessageCreate(BaseModel):
    transaction_id: int

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
    )

    message_type: str = Field(
        default="text",
        max_length=30,
    )

    media_url: str | None = None
    media_type: str | None = None


class MessageResponse(APIBaseModel):
    id: int

    transaction_id: int
    sender_id: int

    content: str
    message_type: str

    media_url: str | None = None
    media_type: str | None = None

    is_system_message: bool
    is_read: bool

    created_at: datetime


# =========================================================
# FAVORITES
# =========================================================

class FavoriteResponse(APIBaseModel):
    id: int

    user_id: int
    listing_id: int

    created_at: datetime


# =========================================================
# REVIEWS
# =========================================================

class ReviewCreate(BaseModel):
    transaction_id: int

    rating: int = Field(
        ...,
        ge=1,
        le=5,
    )

    comment: str | None = Field(
        default=None,
        max_length=3000,
    )


class ReviewResponse(APIBaseModel):
    id: int

    transaction_id: int

    reviewer_id: int
    reviewed_user_id: int

    rating: int
    comment: str | None = None

    is_visible: bool

    created_at: datetime
    updated_at: datetime


# =========================================================
# REPORTS
# =========================================================

class ReportCreate(BaseModel):
    listing_id: int | None = None
    transaction_id: int | None = None

    reason: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )


class ReportResponse(APIBaseModel):
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


# =========================================================
# ADMIN
# =========================================================

class AdminLoginRequest(BaseModel):
    code: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )


class AdminLoginResponse(BaseModel):
    token: str
    expires_in: int


class AdminListingDecision(BaseModel):
    action: str = Field(
        ...,
        description="approve ou reject",
    )

    note: str | None = Field(
        default=None,
        max_length=5000,
    )


class AdminTransactionAction(BaseModel):
    action: str = Field(
        ...,
        description="assign, cancel, dispute, complete, refund",
    )

    note: str | None = Field(
        default=None,
        max_length=5000,
    )


# =========================================================
# PAGINATION
# =========================================================

class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    pages: int


# =========================================================
# GENERIC API
# =========================================================

class MessageResponseSimple(BaseModel):
    status: str
    message: str