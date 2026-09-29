from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, validate_telegram_init_data
from app.config import settings
from app.db import get_db
from app.models.user import User
from app.models.wallet import Wallet


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post("/telegram")
async def authenticate_telegram(
    init_data: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Authentifie un utilisateur depuis Telegram Mini App.

    Le frontend envoie le initData brut fourni par Telegram.
    """

    telegram_data = validate_telegram_init_data(init_data)

    telegram_id = telegram_data["telegram_id"]

    result = await db.execute(
        select(User).where(
            User.telegram_id == telegram_id
        )
    )

    user = result.scalar_one_or_none()

    # ========================================================
    # CRÉATION DU COMPTE
    # ========================================================

    if user is None:
        # Génération d'un Nexa ID interne/public
        nexa_id = f"NX{telegram_id}"

        # Éviter une collision éventuelle
        existing_nexa = await db.execute(
            select(User).where(
                User.nexa_id == nexa_id
            )
        )

        if existing_nexa.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Impossible de créer l'identifiant Nexa.",
            )

        user = User(
            telegram_id=telegram_id,
            username=telegram_data.get("username"),
            first_name=telegram_data.get("first_name"),
            last_name=telegram_data.get("last_name"),
            photo_url=telegram_data.get("photo_url"),
            nexa_id=nexa_id,
            language="fr",
            preferred_currency="XAF",
            is_active=True,
            is_admin=False,
        )

        db.add(user)

        await db.flush()

        # ====================================================
        # WALLET
        # ====================================================

        wallet = Wallet(
            user_id=user.id,
            available_balance=0,
            blocked_balance=0,
            total_revenue=0,
            currency="XAF",
        )

        db.add(wallet)

        await db.commit()

        await db.refresh(user)

    else:
        # ====================================================
        # MISE À JOUR DES DONNÉES TELEGRAM
        # ====================================================

        user.username = telegram_data.get("username")
        user.first_name = telegram_data.get("first_name")
        user.last_name = telegram_data.get("last_name")
        user.photo_url = telegram_data.get("photo_url")

        await db.commit()

        await db.refresh(user)

    # ========================================================
    # VÉRIFICATION DU COMPTE
    # ========================================================

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre compte NexMarket est désactivé.",
        )

    # ========================================================
    # JWT
    # ========================================================

    access_token = create_access_token(
        user.id
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in_minutes": settings.JWT_EXPIRE_MINUTES,
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "photo_url": user.photo_url,
            "nexa_id": user.nexa_id,
            "language": user.language,
            "preferred_currency": user.preferred_currency,
        },
    }
