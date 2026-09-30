from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CurrentAdmin, CurrentUser, DBSession
from app.models.withdrawal import Withdrawal
from app.services.withdrawal_service import (
    WithdrawalService,
    WithdrawalServiceError,
)

router = APIRouter(
    prefix="/withdrawals",
    tags=["Withdrawals"],
)


# ============================================================
# SCHEMAS
# ============================================================


class WithdrawalCreateRequest(BaseModel):
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


class WithdrawalRejectRequest(BaseModel):
    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
    )


class WithdrawalResponse(BaseModel):
    id: int
    reference: str
    amount: Decimal
    currency: str
    status: str
    jessikapay_transaction_id: str | None = None
    failure_reason: str | None = None
    admin_note: str | None = None

    requested_at: str
    processed_at: str | None = None
    completed_at: str | None = None
    rejected_at: str | None = None
    cancelled_at: str | None = None

    class Config:
        from_attributes = True


def serialize_withdrawal(
    withdrawal: Withdrawal,
) -> WithdrawalResponse:

    return WithdrawalResponse(
        id=withdrawal.id,
        reference=withdrawal.reference,
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        status=withdrawal.status,
        jessikapay_transaction_id=(
            withdrawal.jessikapay_transaction_id
        ),
        failure_reason=withdrawal.failure_reason,
        admin_note=withdrawal.admin_note,
        requested_at=withdrawal.requested_at.isoformat(),
        processed_at=(
            withdrawal.processed_at.isoformat()
            if withdrawal.processed_at
            else None
        ),
        completed_at=(
            withdrawal.completed_at.isoformat()
            if withdrawal.completed_at
            else None
        ),
        rejected_at=(
            withdrawal.rejected_at.isoformat()
            if withdrawal.rejected_at
            else None
        ),
        cancelled_at=(
            withdrawal.cancelled_at.isoformat()
            if withdrawal.cancelled_at
            else None
        ),
    )


# ============================================================
# CREATE WITHDRAWAL
# ============================================================


@router.post(
    "",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_withdrawal(
    payload: WithdrawalCreateRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Crée une demande de retrait.

    Le montant est immédiatement déplacé de
    available_balance vers blocked_balance.

    Aucun paiement JessiKaPay n'est considéré comme
    définitif à cette étape.
    """

    service = WithdrawalService(db)

    try:
        withdrawal = await service.create_withdrawal(
            user_id=current_user.id,
            amount=payload.amount,
            currency=payload.currency,
            jp_number=payload.jp_number,
        )

        return serialize_withdrawal(withdrawal)

    except WithdrawalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ============================================================
# MY WITHDRAWALS
# ============================================================


@router.get(
    "/mine",
    response_model=list[WithdrawalResponse],
)
async def get_my_withdrawals(
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
    Retourne uniquement les retraits de l'utilisateur connecté.

    Le numéro JessiKaPay n'est jamais retourné.
    """

    result = await db.execute(
        select(Withdrawal)
        .where(
            Withdrawal.user_id == current_user.id
        )
        .order_by(
            Withdrawal.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    withdrawals = result.scalars().all()

    return [
        serialize_withdrawal(withdrawal)
        for withdrawal in withdrawals
    ]


# ============================================================
# GET MY WITHDRAWAL
# ============================================================


@router.get(
    "/{withdrawal_id}",
    response_model=WithdrawalResponse,
)
async def get_withdrawal(
    withdrawal_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    result = await db.execute(
        select(Withdrawal).where(
            Withdrawal.id == withdrawal_id
        )
    )

    withdrawal = result.scalar_one_or_none()

    if not withdrawal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demande de retrait introuvable.",
        )

    if withdrawal.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    return serialize_withdrawal(withdrawal)


# ============================================================
# CANCEL MY WITHDRAWAL
# ============================================================


@router.post(
    "/{withdrawal_id}/cancel",
    response_model=WithdrawalResponse,
)
async def cancel_withdrawal(
    withdrawal_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    service = WithdrawalService(db)

    try:
        withdrawal = await service.cancel_withdrawal(
            withdrawal_id=withdrawal_id,
            user_id=current_user.id,
        )

        return serialize_withdrawal(withdrawal)

    except WithdrawalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ============================================================
# ADMIN - LIST WITHDRAWALS
# ============================================================


@router.get(
    "/admin/all",
    response_model=list[WithdrawalResponse],
)
async def admin_get_withdrawals(
    current_admin: CurrentAdmin,
    db: DBSession,
    status_filter: str | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=200,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
):
    query = select(Withdrawal)

    if status_filter:
        query = query.where(
            Withdrawal.status == status_filter
        )

    query = (
        query
        .order_by(
            Withdrawal.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    withdrawals = result.scalars().all()

    return [
        serialize_withdrawal(withdrawal)
        for withdrawal in withdrawals
    ]


# ============================================================
# ADMIN - PROCESS WITHDRAWAL
# ============================================================


@router.post(
    "/admin/{withdrawal_id}/process",
    response_model=WithdrawalResponse,
)
async def admin_process_withdrawal(
    withdrawal_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    Lance le payout JessiKaPay.

    Important :
    la réponse de JessiKaPay ne clôture pas encore
    le retrait.

    Le retrait reste payout_sent jusqu'au webhook
    credit.completed.
    """

    service = WithdrawalService(db)

    try:
        withdrawal = await service.process_withdrawal(
            withdrawal_id=withdrawal_id,
        )

        return serialize_withdrawal(withdrawal)

    except WithdrawalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ============================================================
# ADMIN - REJECT WITHDRAWAL
# ============================================================


@router.post(
    "/admin/{withdrawal_id}/reject",
    response_model=WithdrawalResponse,
)
async def admin_reject_withdrawal(
    withdrawal_id: int,
    payload: WithdrawalRejectRequest,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    service = WithdrawalService(db)

    try:
        withdrawal = await service.reject_withdrawal(
            withdrawal_id=withdrawal_id,
            admin_id=current_admin.id,
            reason=payload.reason,
        )

        return serialize_withdrawal(withdrawal)

    except WithdrawalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
