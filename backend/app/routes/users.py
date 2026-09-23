from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.wallet_service import wallet_service


router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


# =========================================================
# MON PROFIL
# =========================================================

@router.get("/me")
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Retourne le profil Telegram/NexMarket de l'utilisateur connecté.
    """

    return {
        "id": current_user.id,
        "nexa_id": current_user.nexa_id,
        "telegram_id": current_user.telegram_id,
        "username": current_user.username,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "photo_url": current_user.photo_url,
        "is_admin": current_user.is_admin,
        "language": current_user.language,
        "currency": current_user.currency,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
    }


# =========================================================
# MON WALLET
# =========================================================

@router.get("/me/wallet")
async def get_my_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne les soldes du portefeuille.
    """

    balance = await wallet_service.get_balance(
        db=db,
        user_id=current_user.id,
    )

    return balance


# =========================================================
# MODIFIER LA LANGUE
# =========================================================

@router.patch("/me/language")
async def update_language(
    language: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Modifie la langue du compte.

    Pour le moment :
    - fr
    - en
    """

    language = language.strip().lower()

    if language not in {"fr", "en"}:
        raise HTTPException(
            status_code=400,
            detail="Langue non supportée.",
        )

    current_user.language = language

    await db.commit()
    await db.refresh(current_user)

    return {
        "status": "success",
        "language": current_user.language,
    }


# =========================================================
# MODIFIER LA DEVISE
# =========================================================

@router.patch("/me/currency")
async def update_currency(
    currency: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Modifie la devise préférée.

    NexMarket utilise actuellement XAF.
    """

    currency = currency.strip().upper()

    if currency != "XAF":
        raise HTTPException(
            status_code=400,
            detail=(
                "Cette devise n'est pas encore disponible "
                "sur NexMarket."
            ),
        )

    current_user.currency = currency

    await db.commit()
    await db.refresh(current_user)

    return {
        "status": "success",
        "currency": current_user.currency,
    }


# =========================================================
# DESACTIVER MON COMPTE
# =========================================================

@router.post("/me/deactivate")
async def deactivate_my_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Désactive le compte NexMarket.

    Le compte Telegram n'est évidemment pas supprimé.
    """

    current_user.is_active = False

    await db.commit()

    return {
        "status": "success",
        "message": "Compte NexMarket désactivé.",
    }