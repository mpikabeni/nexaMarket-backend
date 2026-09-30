from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import CurrentAdmin, CurrentUser
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.user import User
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["transactions"])


async def _get_transaction(
    transaction_id: int,
    db: AsyncSession,
) -> Transaction:
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    return transaction


def _can_access(transaction: Transaction, user: User) -> bool:
    return (
        transaction.buyer_id == user.id
        or transaction.seller_id == user.id
        or transaction.assigned_admin_id == user.id
        or user.is_admin
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_transaction(
    listing_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    listing_result = await db.execute(
        select(Listing).where(Listing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    if listing.seller_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas acheter votre propre annonce.",
        )

    if listing.status not in {"approved", "published"} or not listing.is_public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette annonce n'est pas disponible à l'achat.",
        )

    service = TransactionService(db)

    transaction = await service.create_transaction(
        listing_id=listing.id,
        buyer_id=current_user.id,
    )

    await db.commit()
    await db.refresh(transaction)

    return transaction


@router.get("/mine")
async def my_transactions(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction)
        .where(
            (Transaction.buyer_id == current_user.id)
            | (Transaction.seller_id == current_user.id)
        )
        .order_by(Transaction.created_at.desc())
    )

    return result.scalars().all()


@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    return transaction


@router.post("/{transaction_id}/payment")
async def create_payment(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if transaction.buyer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul l'acheteur peut effectuer le paiement.",
        )

    service = TransactionService(db)

    result = await service.create_payment(
        transaction_id=transaction.id,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/payment/check")
async def check_payment(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = TransactionService(db)

    result = await service.check_payment(
        transaction_id=transaction.id,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/assign")
async def assign_transaction(
    transaction_id: int,
    admin: CurrentAdmin,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    service = TransactionService(db)

    result = await service.assign_admin(
        transaction_id=transaction.id,
        admin_id=admin.id,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/start-transfer")
async def start_transfer(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = TransactionService(db)

    result = await service.start_transfer(
        transaction_id=transaction.id,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/complete-transfer")
async def complete_transfer(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = TransactionService(db)

    result = await service.complete_transfer(
        transaction_id=transaction.id,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/finish-protection")
async def finish_protection(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = TransactionService(db)

    result = await service.finish_protection(
        transaction_id=transaction.id,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/dispute")
async def dispute_transaction(
    transaction_id: int,
    reason: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = TransactionService(db)

    result = await service.open_dispute(
        transaction_id=transaction.id,
        user_id=current_user.id,
        reason=reason,
    )

    await db.commit()

    return result


@router.post("/{transaction_id}/cancel")
async def cancel_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    if not _can_access(transaction, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    service = TransactionService(db)

    result = await service.cancel_transaction(
        transaction_id=transaction.id,
        user_id=current_user.id,
    )

    await db.commit()

    return result
