from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.deposit import Deposit
from app.services.deposit_service import (
    DepositService,
    DepositServiceError,
)


router = APIRouter(
    prefix="/deposits",
    tags=["Deposits"],
)


# ============================================================
# SCHEMAS
# ============================================================


class DepositCreateRequest(BaseModel):
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


class DepositResponse(BaseModel):
    id: int
    reference: str
    amount: Decimal
    currency: str
    country: str
    status: str

    # Ces données sont utiles à l'utilisateur pour
    # effectuer son paiement.
    jessikapay_request_id: str
    jessikapay_code: str | None = None
    payment_link: str | None = None

    commission_amount: Decimal | None = None
    net_amount_credited: Decimal | None = None

    failure_reason: str | None = None

    expires_at: str | None = None
    paid_at: str | None = None
    cancelled_at: str | None = None
    created_at: str

    class Config:
        from_attributes = True


def serialize_deposit(
    deposit: Deposit,
) -> DepositResponse:

    return DepositResponse(
        id=deposit.id,
        reference=deposit.reference,
        amount=deposit.amount,
        currency=deposit.currency,
        country=deposit.country,
        status=deposit.status,
        jessikapay_request_id=(
            deposit.jessikapay_request_id
        ),
        jessikapay_code=deposit.jessikapay_code,
        payment_link=deposit.payment_link,
        commission_amount=(
            deposit.commission_amount
        ),
        net_amount_credited=(
            deposit.net_amount_credited
        ),
        failure_reason=deposit.failure_reason,
        expires_at=(
            deposit.expires_at.isoformat()
            if deposit.expires_at
            else None
        ),
        paid_at=(
            deposit.paid_at.isoformat()
            if deposit.paid_at
            else None
        ),
        cancelled_at=(
            deposit.cancelled_at.isoformat()
            if deposit.cancelled_at
            else None
        ),
        created_at=deposit.created_at.isoformat(),
    )


# ============================================================
# CREATE DEPOSIT
# ============================================================


@router.post(
    "",
    response_model=DepositResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_deposit(
    payload: DepositCreateRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Crée une demande de dépôt JessiKaPay.

    Le portefeuille n'est PAS crédité ici.
    Le crédit intervient uniquement après confirmation
    du paiement.
    """

    service = DepositService(db)

    try:
        deposit = await service.create_deposit(
            user_id=current_user.id,
            amount=payload.amount,
            country=payload.country,
            phone=payload.phone,
            currency=payload.currency,
        )

        return serialize_deposit(deposit)

    except DepositServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ============================================================
# MY DEPOSITS
# ============================================================


@router.get(
    "/mine",
    response_model=list[DepositResponse],
)
async def get_my_deposits(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
):
    """
    Retourne uniquement les dépôts de l'utilisateur connecté.

    Le numéro de téléphone n'est jamais retourné.
    """

    result = await db.execute(
        select(Deposit)
        .where(
            Deposit.user_id == current_user.id
        )
        .order_by(
            Deposit.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    deposits = result.scalars().all()

    return [
        serialize_deposit(deposit)
        for deposit in deposits
    ]


# ============================================================
# GET DEPOSIT
# ============================================================


@router.get(
    "/{deposit_id}",
    response_model=DepositResponse,
)
async def get_deposit(
    deposit_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    result = await db.execute(
        select(Deposit).where(
            Deposit.id == deposit_id
        )
    )

    deposit = result.scalar_one_or_none()

    if not deposit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dépôt introuvable.",
        )

    if deposit.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    return serialize_deposit(deposit)


# ============================================================
# REFRESH STATUS
# ============================================================


@router.post(
    "/{deposit_id}/check",
    response_model=DepositResponse,
)
async def check_deposit(
    deposit_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Vérifie directement l'état du dépôt auprès de JessiKaPay.

    Sert de mécanisme de secours si le webhook n'a pas encore
    été reçu.
    """

    result = await db.execute(
        select(Deposit).where(
            Deposit.id == deposit_id
        )
    )

    deposit = result.scalar_one_or_none()

    if not deposit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dépôt introuvable.",
        )

    if deposit.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = DepositService(db)

    try:
        deposit = await service.refresh_deposit_status(
            deposit_id=deposit_id,
        )

        return serialize_deposit(deposit)

    except DepositServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ============================================================
# CANCEL DEPOSIT
# ============================================================


@router.post(
    "/{deposit_id}/cancel",
    response_model=DepositResponse,
)
async def cancel_deposit(
    deposit_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    service = DepositService(db)

    try:
        deposit = await service.cancel_deposit(
            deposit_id=deposit_id,
            user_id=current_user.id,
        )

        return serialize_deposit(deposit)

    except DepositServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
