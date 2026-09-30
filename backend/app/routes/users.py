from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.deps import CurrentUser, DBSession
from app.models.schemas import UserResponse, UserUpdate


router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


# ============================================================
# GET MY PROFILE
# ============================================================

@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_my_profile(
    current_user: CurrentUser,
):
    """
    Retourne le profil de l'utilisateur connecté.
    """

    return current_user


# ============================================================
# UPDATE MY PROFILE
# ============================================================

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
    Met à jour les préférences du profil.

    Les informations d'identité Telegram ne doivent pas
    être utilisées pour modifier l'identité réelle du compte.
    """

    data = payload.model_dump(
        exclude_unset=True
    )

    # --------------------------------------------------------
    # Champs autorisés
    # --------------------------------------------------------

    allowed_fields = {
        "language",
        "preferred_currency",
    }

    # On ne permet pas au frontend de modifier :
    # - telegram_id
    # - nexa_id
    # - is_admin
    # - is_active
    # - identité Telegram
    # - photo Telegram
    #
    # Ces données sont contrôlées par le backend/Telegram.

    for field in data:
        if field not in allowed_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Le champ '{field}' "
                    "ne peut pas être modifié."
                ),
            )

    # --------------------------------------------------------
    # Language
    # --------------------------------------------------------

    if "language" in data:
        language = data["language"]

        if language is not None:
            language = language.strip().lower()

            if len(language) > 10:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Langue invalide.",
                )

            current_user.language = language

    # --------------------------------------------------------
    # Currency
    # --------------------------------------------------------

    if "preferred_currency" in data:
        currency = data[
            "preferred_currency"
        ]

        if currency is not None:
            currency = currency.strip().upper()

            supported_currencies = set(
                settings.get_supported_currencies()
            )

            if currency not in supported_currencies:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Devise non supportée. "
                        f"Devises disponibles : "
                        f"{', '.join(sorted(supported_currencies))}"
                    ),
                )

            current_user.preferred_currency = (
                currency
            )

    await db.commit()
    await db.refresh(current_user)

    return current_user


# ============================================================
# GET MY WALLET SUMMARY
# ============================================================

@router.get("/me/wallet")
async def get_my_wallet(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne le wallet de l'utilisateur connecté.
    """

    if current_user.wallet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet introuvable.",
        )

    wallet = current_user.wallet

    return {
        "id": wallet.id,
        "available_balance": (
            wallet.available_balance
        ),
        "blocked_balance": (
            wallet.blocked_balance
        ),
        "total_revenue": (
            wallet.total_revenue
        ),
        "currency": wallet.currency,
        "created_at": wallet.created_at,
        "updated_at": wallet.updated_at,
    }
