from fastapi import APIRouter, HTTPException, Query

from app.deps import CurrentUser, DBSession
from app.services.wallet_service import (
    WalletService,
    WalletServiceError,
)


router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
)


@router.get("/balance")
async def get_balance(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne le solde du wallet de l'utilisateur connecté.
    """

    service = WalletService(db)

    try:
        return await service.get_balance(
            current_user.id
        )
    except WalletServiceError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@router.get("/operations")
async def get_operations(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
):
    """
    Retourne l'historique des opérations du wallet.
    """

    service = WalletService(db)

    try:
        operations = await service.get_operations(
            user_id=current_user.id,
            limit=limit,
        )
    except WalletServiceError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return {
        "operations": [
            {
                "id": operation.id,
                "operation_type": operation.operation_type,
                "amount": operation.amount,
                "currency": operation.currency,
                "status": operation.status,
                "provider_reference": (
                    operation.provider_reference
                ),
                "reference": operation.reference,
                "description": operation.description,
                "created_at": operation.created_at,
            }
            for operation in operations
        ]
    }
