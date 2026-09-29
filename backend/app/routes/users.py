from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.schemas import UserResponse, UserUpdate
from app.models.wallet import Wallet


router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_my_profile(
    current_user: CurrentUser,
):
    """
    Retourne le profil de l'utilisateur connecté.

    Les données sensibles comme is_admin ne sont pas
    exposées par UserResponse.
    """

    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
)
async def update_my_profile(
    payload: UserUpdate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Modifie les informations de profil autorisées.
    """

    if payload.username is not None:
        current_user.username = payload.username

    if payload.first_name is not None:
        current_user.first_name = payload.first_name

    if payload.last_name is not None:
        current_user.last_name = payload.last_name

    if payload.photo_url is not None:
        current_user.photo_url = payload.photo_url

    if payload.language is not None:
        current_user.language = payload.language

    if payload.preferred_currency is not None:
        allowed_currencies = {
            currency.upper()
            for currency in settings.get_supported_currencies()
        }

        currency = payload.preferred_currency.upper()

        if currency not in allowed_currencies:
            raise HTTPException(
                status_code=400,
                detail="Devise non supportée.",
            )

        current_user.preferred_currency = currency

    await db.commit()
    await db.refresh(current_user)

    return current_user


@router.get(
    "/me/wallet",
)
async def get_my_wallet(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne le wallet de l'utilisateur connecté.
    """

    result = await db.execute(
        select(Wallet).where(
            Wallet.user_id == current_user.id
        )
    )

    wallet = result.scalar_one_or_none()

    if wallet is None:
        raise HTTPException(
            status_code=404,
            detail="Wallet introuvable.",
        )

    return {
        "id": wallet.id,
        "available_balance": wallet.available_balance,
        "blocked_balance": wallet.blocked_balance,
        "total_revenue": wallet.total_revenue,
        "currency": wallet.currency,
    }
