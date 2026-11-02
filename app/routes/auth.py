from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, validate_telegram_init_data
from app.config import settings
from app.db import get_db
from app.models.user import User
from app.models.wallet import Wallet
from app.services.telegram_service import get_telegram_service


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


class TelegramAuthRequest(BaseModel):
    init_data: str


_ACCESS_MESSAGES = {
    "bot_not_started": (
        "Démarre d'abord le bot NexMarket (appuie sur « Démarrer » / "
        "/start), puis reviens ouvrir la Mini App."
    ),
    "channel_required": (
        "Pour utiliser NexMarket, rejoins d'abord notre canal officiel "
        "NEXA, puis reviens ouvrir la Mini App."
    ),
}


async def _access_denied(code: str) -> HTTPException:
    """403 structuré : le frontend affiche un écran avec les boutons."""

    service = get_telegram_service()
    username = await service.bot_username()

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": code,
            "message": _ACCESS_MESSAGES[code],
            "bot_username": username,
            "bot_url": (
                f"https://t.me/{username}?start=app" if username else ""
            ),
            "channel_url": settings.REQUIRED_CHANNEL_URL,
        },
    )


# POST /api/auth  et  POST /api/auth/telegram  (même comportement)
@router.post("")
@router.post("/telegram")
async def authenticate_telegram(
    payload: TelegramAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authentifie un utilisateur depuis Telegram Mini App.

    Le frontend envoie le initData brut fourni par Telegram.
    """

    telegram_data = validate_telegram_init_data(payload.init_data)

    telegram_id = telegram_data["telegram_id"]

    result = await db.execute(
        select(User).where(
            User.telegram_id == telegram_id
        )
    )

    user = result.scalar_one_or_none()

    # ========================================================
    # OBLIGATION : bot démarré + canal NEXA rejoint
    # ========================================================
    # Les administrateurs en sont dispensés. Aucun compte n'est créé tant
    # que l'utilisateur n'a pas démarré le bot.

    is_admin_account = (
        bool(settings.ADMIN_TELEGRAM_ID)
        and telegram_id == settings.ADMIN_TELEGRAM_ID
    ) or bool(user and user.is_admin)

    if settings.REQUIRE_BOT_AND_CHANNEL and not is_admin_account:
        missing = await get_telegram_service().check_user_access(
            int(telegram_id)
        )

        if missing:
            raise await _access_denied(missing)

    # ========================================================
    # CRÉATION DU COMPTE
    # ========================================================

    if user is None:
        # Nexa ID public : ALÉATOIRE. Avant il valait "NX<telegram_id>",
        # ce qui exposait publiquement l'identifiant Telegram privé.
        nexa_id = None

        for _ in range(5):
            candidate = f"NX{uuid4().hex[:8].upper()}"

            taken = await db.execute(
                select(User.id).where(User.nexa_id == candidate)
            )

            if taken.first() is None:
                nexa_id = candidate
                break

        if nexa_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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

        try:
            await db.flush()

            db.add(
                Wallet(
                    user_id=user.id,
                    available_balance=0,
                    blocked_balance=0,
                    total_revenue=0,
                    currency="XAF",
                )
            )

            await db.commit()

        except IntegrityError:
            # Deux premières connexions simultanées : l'autre requête
            # a créé le compte entre-temps. On le relit.
            await db.rollback()

            result = await db.execute(
                select(User).where(User.telegram_id == telegram_id)
            )

            user = result.scalar_one_or_none()

            if user is None:
                raise

        await db.refresh(user)

    else:
        # ====================================================
        # MISE À JOUR DES DONNÉES TELEGRAM
        # ====================================================

        # Telegram n'envoie pas toujours photo_url (confidentialité,
        # mode d'ouverture de la Mini App) : une valeur ABSENTE ne doit
        # jamais effacer ce qui est déjà enregistré.
        if telegram_data.get("first_name"):
            user.first_name = telegram_data["first_name"]

        # last_name / username peuvent légitimement être supprimés par
        # l'utilisateur ; on ne les met à jour que si first_name est fourni
        # (donnée Telegram complète).
        if telegram_data.get("first_name"):
            user.last_name = telegram_data.get("last_name")
            user.username = telegram_data.get("username")

        if telegram_data.get("photo_url"):
            user.photo_url = telegram_data["photo_url"]

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
