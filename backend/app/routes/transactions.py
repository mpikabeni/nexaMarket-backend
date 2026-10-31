from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import CurrentAdmin, CurrentUser
from app.models.listing import Listing
from app.models.schemas import (
    DisputeRequest,
    ResolveRequest,
    TransactionCreate,
    TransactionResponse,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ============================================================
# HELPERS
# ============================================================

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
        or user.is_admin
    )


async def _get_accessible(
    transaction_id: int,
    user: User,
    db: AsyncSession,
) -> Transaction:
    transaction = await _get_transaction(transaction_id, db)

    # 404 (et non 403) : on ne révèle pas l'existence de la transaction.
    if not _can_access(transaction, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    return transaction


async def _present(
    transactions: list[Transaction],
    db: AsyncSession,
) -> list[TransactionResponse]:
    """
    Ajoute les champs d'affichage lus par le frontend
    (titre de l'annonce, noms acheteur / vendeur).
    Les notes internes admin ne sont jamais exposées.
    """

    if not transactions:
        return []

    listing_ids = {t.listing_id for t in transactions}
    user_ids = {t.buyer_id for t in transactions} | {
        t.seller_id for t in transactions
    }

    titles = dict(
        (
            await db.execute(
                select(Listing.id, Listing.title).where(
                    Listing.id.in_(listing_ids)
                )
            )
        ).all()
    )

    names = {}

    for user in (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars():
        names[user.id] = (
            user.first_name
            or (f"@{user.username}" if user.username else None)
            or user.nexa_id
        )

    result = []

    for transaction in transactions:
        item = TransactionResponse.model_validate(transaction)

        result.append(
            item.model_copy(
                update={
                    "listing_title": titles.get(transaction.listing_id),
                    "buyer_name": names.get(transaction.buyer_id),
                    "seller_name": names.get(transaction.seller_id),
                }
            )
        )

    return result


async def _one(transaction: Transaction, db: AsyncSession):
    return (await _present([transaction], db))[0]


# ============================================================
# ACHAT (création + blocage des fonds du wallet)
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TransactionResponse,
)
async def create_transaction(
    payload: TransactionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    service = TransactionService(db)

    # Solde insuffisant / annonce indisponible : erreurs 400 gérées
    # par les handlers globaux de main.py.
    transaction = await service.purchase(
        buyer_id=current_user.id,
        listing_id=payload.listing_id,
    )

    return await _one(transaction, db)


# ============================================================
# LECTURE
# ============================================================

@router.get("/mine", response_model=list[TransactionResponse])
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
        .limit(200)
    )

    return await _present(list(result.scalars().all()), db)


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_accessible(
        transaction_id, current_user, db
    )

    return await _one(transaction, db)


# ============================================================
# ACTIONS ADMIN (transfert du canal)
# ============================================================

@router.post("/{transaction_id}/assign", response_model=TransactionResponse)
async def assign_transaction(
    transaction_id: int,
    admin: CurrentAdmin,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    result = await TransactionService(db).assign_admin(
        transaction_id=transaction.id,
        admin_id=admin.id,
    )

    return await _one(result, db)


@router.post(
    "/{transaction_id}/start-transfer",
    response_model=TransactionResponse,
)
async def start_transfer(
    transaction_id: int,
    admin: CurrentAdmin,
    db: AsyncSession = Depends(get_db),
):
    # Réservé à l'administration : sinon le vendeur pourrait lancer
    # lui-même le compte à rebours de libération des fonds.
    transaction = await _get_transaction(transaction_id, db)

    result = await TransactionService(db).start_transfer(
        transaction_id=transaction.id
    )

    return await _one(result, db)


@router.post(
    "/{transaction_id}/complete-transfer",
    response_model=TransactionResponse,
)
async def complete_transfer(
    transaction_id: int,
    admin: CurrentAdmin,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_transaction(transaction_id, db)

    result = await TransactionService(db).complete_transfer(
        transaction_id=transaction.id
    )

    return await _one(result, db)


@router.post(
    "/{transaction_id}/resolve",
    response_model=TransactionResponse,
)
async def resolve_transaction(
    transaction_id: int,
    payload: ResolveRequest,
    admin: CurrentAdmin,
    db: AsyncSession = Depends(get_db),
):
    """
    Tranche une transaction (admin) :
      - refund_buyer   : les fonds bloqués retournent à l'acheteur ;
      - release_seller : le vendeur est payé (prix - commission).
    """

    transaction = await _get_transaction(transaction_id, db)

    result = await TransactionService(db).resolve(
        transaction_id=transaction.id,
        action=payload.action,
        admin_id=admin.id,
        note=payload.note,
    )

    return await _one(result, db)


# ============================================================
# ACTIONS ACHETEUR / VENDEUR
# ============================================================

@router.post(
    "/{transaction_id}/finish-protection",
    response_model=TransactionResponse,
)
async def finish_protection(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_accessible(
        transaction_id, current_user, db
    )

    result = await TransactionService(db).finish_protection(
        transaction_id=transaction.id
    )

    return await _one(result, db)


@router.post(
    "/{transaction_id}/confirm-receipt",
    response_model=TransactionResponse,
)
async def confirm_receipt(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """L'acheteur confirme avoir reçu le canal : le vendeur est payé."""

    transaction = await _get_accessible(
        transaction_id, current_user, db
    )

    result = await TransactionService(db).confirm_receipt(
        transaction_id=transaction.id,
        user_id=current_user.id,
    )

    return await _one(result, db)


@router.post(
    "/{transaction_id}/dispute",
    response_model=TransactionResponse,
)
async def dispute_transaction(
    transaction_id: int,
    payload: DisputeRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_accessible(
        transaction_id, current_user, db
    )

    result = await TransactionService(db).open_dispute(
        transaction_id=transaction.id,
        user_id=current_user.id,
        reason=payload.reason,
    )

    return await _one(result, db)


@router.post(
    "/{transaction_id}/cancel",
    response_model=TransactionResponse,
)
async def cancel_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    transaction = await _get_accessible(
        transaction_id, current_user, db
    )

    result = await TransactionService(db).cancel_transaction(
        transaction_id=transaction.id,
        user_id=current_user.id,
    )

    return await _one(result, db)
