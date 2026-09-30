from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DBSession
from app.models.schemas import DepositRequest
from app.services.jessikapay_service import (
    JessiKaPayError,
    JessiKaPayService,
)


router = APIRouter(
    prefix="/deposits",
    tags=["Deposits"],
)


# ============================================================
# CREATE DEPOSIT
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_deposit(
    payload: DepositRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Crée une demande de dépôt via JessiKaPay.

    Le dépôt est destiné au compte NexMarket de l'utilisateur.
    Le backend ne crédite pas le wallet tant que JessiKaPay
    n'a pas confirmé le paiement.
    """

    # --------------------------------------------------------
    # Validation du montant
    # --------------------------------------------------------

    if payload.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le montant doit être supérieur à zéro.",
        )

    # --------------------------------------------------------
    # Devise
    # --------------------------------------------------------

    currency = (
        payload.currency
        if getattr(payload, "currency", None)
        else current_user.preferred_currency
    )

    currency = currency.upper()

    if currency != "XAF":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Les dépôts JessiKaPay sont actuellement "
                "limités au XAF."
            ),
        )

    # --------------------------------------------------------
    # Configuration JessiKaPay
    # --------------------------------------------------------

    jessikapay = JessiKaPayService()

    # --------------------------------------------------------
    # Nom de l'utilisateur
    # --------------------------------------------------------

    name_parts = [
        current_user.first_name or "",
        current_user.last_name or "",
    ]

    full_name = " ".join(
        part.strip()
        for part in name_parts
        if part and part.strip()
    ).strip()

    if not full_name:
        full_name = (
            current_user.username
            or f"Utilisateur {current_user.id}"
        )

    # --------------------------------------------------------
    # Téléphone
    # --------------------------------------------------------
    #
    # Le modèle User actuel ne contient pas de numéro
    # de téléphone confirmé.
    #
    # On utilise donc uniquement le champ s'il existe
    # dans le payload. Sinon, on refuse proprement plutôt
    # que d'inventer un numéro.
    # --------------------------------------------------------

    phone = getattr(
        payload,
        "phone",
        None,
    )

    if not phone:
        phone = getattr(
            current_user,
            "phone_number",
            None,
        )

    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Un numéro de téléphone est nécessaire "
                "pour créer le dépôt JessiKaPay."
            ),
        )

    phone = str(phone).strip()

    if len(phone) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Numéro de téléphone invalide.",
        )

    # --------------------------------------------------------
    # Référence
    # --------------------------------------------------------

    reference = getattr(
        payload,
        "reference",
        None,
    )

    if not reference:
        reference = (
            f"NMX-DEP-{current_user.id}-"
            f"{int(__import__('time').time())}"
        )

    reference = str(reference).strip()

    # --------------------------------------------------------
    # Création JessiKaPay
    # --------------------------------------------------------

    try:
        response = (
            await jessikapay.create_deposit_request(
                telegram_id=str(
                    current_user.telegram_id
                ),
                name=full_name,
                country="CG",
                phone=phone,
                amount=int(payload.amount),
                reference=reference,
            )
        )

    except JessiKaPayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"JessiKaPay a refusé le dépôt : {exc}"
            ),
        ) from exc

    request_id = response.get(
        "request_id"
    )

    if not request_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "JessiKaPay n'a pas retourné "
                "de request_id."
            ),
        )

    # --------------------------------------------------------
    # Réponse
    # --------------------------------------------------------

    return {
        "status": response.get(
            "status",
            "pending",
        ),
        "request_id": request_id,
        "code": response.get("code"),
        "payment_link": response.get(
            "payment_link"
        ),
        "amount": response.get(
            "amount",
            payload.amount,
        ),
        "currency": "XAF",
        "reference": reference,
        "expires_at": response.get(
            "expires_at"
        ),
    }


# ============================================================
# CHECK DEPOSIT
# ============================================================

@router.get(
    "/{request_id}/status",
)
async def get_deposit_status(
    request_id: str,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Vérifie le statut d'un dépôt auprès de JessiKaPay.

    Le wallet n'est pas crédité directement par cette route.
    Le crédit doit être effectué uniquement après confirmation
    d'un événement deposit.completed ou d'un mécanisme de
    confirmation prévu par le service.
    """

    if not request_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="request_id invalide.",
        )

    jessikapay = JessiKaPayService()

    try:
        response = (
            await jessikapay.get_deposit_status(
                request_id.strip()
            )
        )

    except JessiKaPayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "request_id": request_id,
        "status": response.get("status"),
        "amount": response.get("amount"),
        "expires_at": response.get("expires_at"),
        "reference": response.get("reference"),
    }
