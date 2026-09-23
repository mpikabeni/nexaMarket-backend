from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import validate_telegram_init_data
from app.db import get_db
from app.models.user import User


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# =========================================================
# UTILITAIRE : CREER / RECUPERER UN UTILISATEUR TELEGRAM
# =========================================================

async def get_or_create_user(
    db: AsyncSession,
    telegram_user: dict,
) -> User:

    telegram_id = telegram_user.get("id")

    if not telegram_id:
        raise HTTPException(
            status_code=400,
            detail="Identifiant Telegram manquant.",
        )

    result = await db.execute(
        select(User).where(
            User.telegram_id == int(telegram_id)
        )
    )

    user = result.scalar_one_or_none()

    if user:
        # Mise à jour des informations Telegram
        # disponibles.
        if telegram_user.get("first_name"):
            user.first_name = telegram_user.get(
                "first_name"
            )

        if telegram_user.get("last_name"):
            user.last_name = telegram_user.get(
                "last_name"
            )

        if telegram_user.get("username"):
            user.username = telegram_user.get(
                "username"
            )

        if telegram_user.get("photo_url"):
            user.photo_url = telegram_user.get(
                "photo_url"
            )

        await db.flush()

        return user

    # =====================================================
    # CREATION DU COMPTE
    # =====================================================

    # Le NEXA ID est interne à NexMarket.
    # Il ne remplace pas l'identifiant Telegram.
    result = await db.execute(
        select(User.id)
        .order_by(User.id.desc())
        .limit(1)
    )

    last_id = result.scalar_one_or_none()

    next_id = (
        int(last_id or 0) + 1
    )

    nexa_id = f"NEXA-{next_id:06d}"

    user = User(
        telegram_id=int(telegram_id),
        nexa_id=nexa_id,

        first_name=telegram_user.get(
            "first_name"
        ),
        last_name=telegram_user.get(
            "last_name"
        ),
        username=telegram_user.get(
            "username"
        ),
        photo_url=telegram_user.get(
            "photo_url"
        ),

        is_active=True,
        is_admin=False,
    )

    db.add(user)

    await db.flush()

    return user


# =========================================================
# LOGIN TELEGRAM MINI APP
# =========================================================

@router.post("/telegram")
async def telegram_login(
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Authentifie un utilisateur depuis Telegram Mini App.

    Le frontend doit envoyer :

    X-Telegram-Init-Data: <initData Telegram>

    Aucun mot de passe ou email n'est nécessaire.
    """

    if not x_telegram_init_data:
        raise HTTPException(
            status_code=401,
            detail=(
                "X-Telegram-Init-Data est obligatoire."
            ),
        )

    try:
        telegram_user = validate_telegram_init_data(
            x_telegram_init_data
        )

    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="Données Telegram invalides.",
        ) from exc

    if not telegram_user:
        raise HTTPException(
            status_code=401,
            detail="Utilisateur Telegram introuvable.",
        )

    user = await get_or_create_user(
        db,
        telegram_user,
    )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Compte NexMarket désactivé.",
        )

    await db.commit()

    return {
        "authenticated": True,
        "user": {
            "id": user.id,
            "nexa_id": user.nexa_id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "photo_url": user.photo_url,
            "is_admin": user.is_admin,
            "language": user.language,
            "currency": user.currency,
        },
    }