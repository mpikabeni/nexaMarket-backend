from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# BASE
# ============================================================

class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
    language: str
    preferred_currency: str
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    photo_url: str | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10)
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


# ============================================================
# CHANNEL
# ============================================================

class ChannelCreate(BaseModel):
    telegram_channel_id: int
    telegram_username: str | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ChannelResponse(APIModel):
    id: int
    telegram_channel_id: int
    telegram_username: str | None = None
    title: str
    photo_url: str | None = None
    description: str | None = None
    subscriber_count: int
    verification_status: str
    bot_is_admin: bool
    bot_permissions_verified: bool
    owner_verified: bool
    is_active: bool
    is_listed: bool
    created_at: datetime


# ============================================================
# LISTING
# ============================================================

class ListingCreate(BaseModel):
    channel_id: int

    price: Decimal = Field(
        gt=0,
        decimal_places=2,
    )

    currency: str = Field(
        min_length=3,
        max_length=10,
    )

    title: str = Field(
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
    """
    Réponse publique.

    IMPORTANT :
    seller_id n'est volontairement PAS présent.
    """

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


# ============================================================
# TRANSACTION
# ============================================================

class TransactionCreate(BaseModel):
    listing_id: int


class TransactionResponse(APIModel):
    id: int
    reference: str
    listing_id: int
    channel_price: Decimal
    platform_fee: Decimal
    provider_fee: Decimal
    total_buyer_amount: Decimal
    seller_amount: Decimal
    currency: str
    platform_fee_rate: Decimal
    status: str
    payment_provider: str | None = None
    payment_status: str | None = None
    escrow_held: bool
    protection_ends_at: datetime | None = None
    created_at: datetime


# ============================================================
# MESSAGES
# ============================================================

class MessageCreate(BaseModel):
    content: str | None = Field(
        default=None,
        max_length=5000,
    )

    message_type: Literal[
        "text",
        "image",
        "document",
    ] = "text"

    attachment_url: str | None = None
    attachment_file_id: str | None = None


class MessageResponse(APIModel):
    id: int
    transaction_id: int
    sender_role: str
    content: str | None = None
    message_type: str
    attachment_url: str | None = None
    attachment_file_id: str | None = None
    is_system_message: bool
    is_read: bool
    created_at: datetime


# ============================================================
# REPORT / LITIGE
# ============================================================

class ReportCreate(BaseModel):
    transaction_id: int

    report_type: str = Field(
        min_length=2,
        max_length=50,
    )

    reason: str = Field(
        min_length=5,
        max_length=5000,
    )


class ReportResponse(APIModel):
    id: int
    transaction_id: int
    report_type: str
    reason: str
    status: str
    admin_resolution: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


# ============================================================
# REVIEW
# ============================================================

class ReviewCreate(BaseModel):
    transaction_id: int

    reviewed_user_id: int

    rating: int = Field(
        ge=1,
        le=5,
    )

    comment: str | None = Field(
        default=None,
        max_length=2000,
    )


class ReviewResponse(APIModel):
    id: int
    transaction_id: int
    reviewer_id: int
    reviewed_user_id: int
    rating: int
    comment: str | None = None
    is_visible: bool
    created_at: datetime


# ============================================================
# FAVORITES
# ============================================================

class FavoriteCreate(BaseModel):
    listing_id: int


class FavoriteResponse(APIModel):
    id: int
    listing_id: int
    created_at: datetime


# ============================================================
# ADMIN REVIEW
# ============================================================

class ListingModeration(BaseModel):
    action: Literal[
        "approve",
        "reject",
        "suspend",
    ]

    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


class ChannelModeration(BaseModel):
    action: Literal[
        "approve",
        "reject",
        "suspend",
    ]

    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


# ============================================================
# TRANSACTION ADMIN ACTIONS
# ============================================================

class TransactionAdminAction(BaseModel):
    action: Literal[
        "assign",
        "start_transfer",
        "validate_transfer",
        "resolve_dispute",
        "refund",
        "cancel",
    ]

    note: str | None = Field(
        default=None,
        max_length=5000,
    )


# ============================================================
# JESSIKAPAY
# ============================================================

class DepositRequest(BaseModel):
    amount: int = Field(gt=0)
    country: str = Field(min_length=2, max_length=10)
    phone: str = Field(min_length=5, max_length=30)
    name: str = Field(min_length=1, max_length=255)


class WithdrawalRequest(BaseModel):
    amount: int = Field(gt=0)
    jp_number: str = Field(min_length=3, max_length=50)


# ============================================================
# PAGINATION
# ============================================================

class PaginationResponse(BaseModel):
    page: int
    limit: int
    total: int
    pages: int
