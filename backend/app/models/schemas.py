from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# BASE
# ============================================================


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
    )


# ============================================================
# USER
# ============================================================


class UserResponse(APIModel):
    id: int
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    photo_url: str | None = None
    nexa_id: str
    is_active: bool
    language: str
    preferred_currency: str
    created_at: datetime


class UserUpdate(BaseModel):
    language: str | None = Field(
        default=None,
        min_length=2,
        max_length=10,
    )

    preferred_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=10,
    )


# ============================================================
# WALLET
# ============================================================


class WalletResponse(APIModel):
    id: int
    available_balance: Decimal
    blocked_balance: Decimal
    total_revenue: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime


class WalletOperationResponse(APIModel):
    id: int
    operation_type: str
    amount: Decimal
    currency: str
    status: str
    provider_reference: str | None = None
    reference: str
    description: str | None = None
    created_at: datetime


# ============================================================
# CHANNEL
# ============================================================


class ChannelCreate(BaseModel):
    telegram_channel_id: int
    telegram_username: str | None = None
    title: str
    description: str | None = None


class ChannelResponse(APIModel):
    id: int
    telegram_channel_id: int
    telegram_username: str | None = None
    title: str
    photo_url: str | None = None
    description: str | None = None
    subscriber_count: int

    bot_is_admin: bool
    bot_permissions_verified: bool
    owner_verified: bool

    verification_status: str
    verified_at: datetime | None = None

    is_active: bool
    is_listed: bool

    created_at: datetime
    updated_at: datetime


class ChannelModeration(BaseModel):
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


# ============================================================
# LISTING
# ============================================================


class ListingCreate(BaseModel):
    channel_id: int

    price: Decimal = Field(
        ...,
        gt=0,
        decimal_places=2,
    )

    currency: str = Field(
        default="XAF",
        min_length=3,
        max_length=10,
    )

    title: str = Field(
        ...,
        min_length=3,
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


class ListingUpdate(BaseModel):
    price: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
    )

    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=10,
    )

    title: str | None = Field(
        default=None,
        min_length=3,
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


class ListingPublicResponse(APIModel):
    id: int
    channel_id: int

    price: Decimal
    currency: str

    title: str
    description: str | None = None
    category: str | None = None

    status: str
    is_public: bool
    published_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class ListingModeration(BaseModel):
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


# ============================================================
# TRANSACTION
# ============================================================


class TransactionCreate(BaseModel):
    listing_id: int


class TransactionResponse(APIModel):
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
    platform_fee_rate: Decimal

    status: str

    payment_provider: str | None = None
    payment_reference: str | None = None
    jessikapay_request_id: str | None = None
    payment_status: str | None = None
    payment_confirmed_at: datetime | None = None

    escrow_held: bool
    escrow_held_at: datetime | None = None

    transfer_started_at: datetime | None = None
    transfer_completed_at: datetime | None = None
    protection_ends_at: datetime | None = None

    buyer_confirmed_at: datetime | None = None

    dispute_reason: str | None = None
    disputed_at: datetime | None = None
    dispute_resolved_at: datetime | None = None

    seller_paid_at: datetime | None = None
    seller_payout_reference: str | None = None
    jessikapay_payout_transaction_id: str | None = None

    nexmarket_fee_recorded_at: datetime | None = None

    cancelled_at: datetime | None = None
    refunded_at: datetime | None = None
    refund_reference: str | None = None

    admin_notes: str | None = None

    created_at: datetime
    updated_at: datetime


class TransactionAdminAction(BaseModel):
    note: str | None = Field(
        default=None,
        max_length=3000,
    )


# ============================================================
# MESSAGE
# ============================================================


class MessageCreate(BaseModel):
    content: str | None = Field(
        default=None,
        max_length=10000,
    )

    message_type: str = Field(
        default="text",
        max_length=20,
    )

    attachment_url: str | None = Field(
        default=None,
        max_length=1000,
    )

    attachment_file_id: str | None = Field(
        default=None,
        max_length=500,
    )


class MessageResponse(APIModel):
    id: int
    transaction_id: int

    sender_id: int
    sender_role: str

    content: str | None = None
    message_type: str

    attachment_url: str | None = None
    attachment_file_id: str | None = None

    is_system_message: bool
    is_read: bool
    read_at: datetime | None = None

    is_deleted: bool
    deleted_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


# ============================================================
# REPORT
# ============================================================


class ReportCreate(BaseModel):
    transaction_id: int

    report_type: str = Field(
        ...,
        min_length=2,
        max_length=50,
    )

    reason: str = Field(
        ...,
        min_length=3,
        max_length=5000,
    )


class ReportResponse(APIModel):
    id: int
    transaction_id: int
    reporter_id: int

    report_type: str
    reason: str

    status: str

    assigned_admin_id: int | None = None
    admin_resolution: str | None = None
    resolved_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


# ============================================================
# REVIEW
# ============================================================


class ReviewCreate(BaseModel):
    rating: int = Field(
        ...,
        ge=1,
        le=5,
    )

    comment: str | None = Field(
        default=None,
        max_length=3000,
    )


class ReviewResponse(APIModel):
    id: int

    transaction_id: int
    reviewer_id: int
    reviewed_user_id: int

    rating: int
    comment: str | None = None

    is_visible: bool

    moderated_by_admin_id: int | None = None
    moderated_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


# ============================================================
# FAVORITE
# ============================================================


class FavoriteCreate(BaseModel):
    listing_id: int


class FavoriteResponse(APIModel):
    id: int
    user_id: int
    listing_id: int
    created_at: datetime


# ============================================================
# DEPOSIT
# ============================================================


class DepositRequest(BaseModel):
    amount: Decimal = Field(
        ...,
        gt=0,
        decimal_places=2,
    )

    country: str = Field(
        ...,
        min_length=2,
        max_length=10,
    )

    phone: str = Field(
        ...,
        min_length=3,
        max_length=50,
    )

    currency: str = Field(
        default="XAF",
        min_length=3,
        max_length=10,
    )


class DepositResponse(APIModel):
    id: int
    reference: str

    amount: Decimal
    currency: str
    country: str

    status: str

    jessikapay_request_id: str
    jessikapay_code: str | None = None
    payment_link: str | None = None

    commission_amount: Decimal | None = None
    net_amount_credited: Decimal | None = None

    failure_reason: str | None = None

    expires_at: datetime | None = None
    paid_at: datetime | None = None
    cancelled_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


# ============================================================
# WITHDRAWAL
# ============================================================


class WithdrawalRequest(BaseModel):
    amount: Decimal = Field(
        ...,
        gt=0,
        decimal_places=2,
    )

    currency: str = Field(
        default="XAF",
        min_length=3,
        max_length=10,
    )

    jp_number: str = Field(
        ...,
        min_length=3,
        max_length=100,
    )


class WithdrawalResponse(APIModel):
    id: int
    reference: str

    amount: Decimal
    currency: str

    status: str

    jessikapay_transaction_id: str | None = None

    failure_reason: str | None = None
    admin_note: str | None = None

    requested_at: datetime
    processed_at: datetime | None = None
    completed_at: datetime | None = None
    rejected_at: datetime | None = None
    cancelled_at: datetime | None = None


class WithdrawalReject(BaseModel):
    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
    )


# ============================================================
# PLATFORM
# ============================================================


class PlatformWalletResponse(APIModel):
    id: int
    currency: str

    available_balance: Decimal
    blocked_balance: Decimal
    total_revenue: Decimal
    total_fees_collected: Decimal

    created_at: datetime
    updated_at: datetime


class PlatformLedgerResponse(APIModel):
    id: int
    wallet_id: int
    transaction_id: int | None = None

    reference: str
    operation_type: str

    amount: Decimal
    currency: str

    description: str | None = None

    created_at: datetime


# ============================================================
# PAGINATION
# ============================================================


class PaginationResponse(BaseModel):
    page: int
    limit: int
    total: int
    pages: int
