from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.deps import DBSession
from app.services.transaction_service import (
    TransactionService,
    TransactionServiceError,
)
from app.services.withdrawal_service import (
    WithdrawalService,
    WithdrawalServiceError,
)


router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


# ============================================================
# WEBHOOK SCHEMA
# ============================================================


class JessiKaPayWebhook(BaseModel):
    event: str
    app_id: str | None = None
    timestamp: str | int | None = None

    # Payment
    request_id: str | None = None
    payment_request_id: str | None = None

    # Credit / payout
    transaction_id: str | None = None
    jp_number: str | None = None
    telegram_id: int | str | None = None

    # Amount
    amount: Decimal | None = None

    # References
    reference: str | None = None

    # Deposit
    commission_amount: Decimal | None = None
    net_amount_credited: Decimal | None = None


# ============================================================
# WEBHOOK
# ============================================================


@router.post(
    "/jessikapay",
    status_code=status.HTTP_200_OK,
)
async def jessikapay_webhook(
    payload: JessiKaPayWebhook,
    db: DBSession,
):
    """
    Réception des événements JessiKaPay.

    Événements pris en charge :

    - payment.completed
    - credit.completed
    - deposit.completed

    IMPORTANT :

    La documentation JessiKaPay fournie ne définit pas de
    signature pour les webhooks entrants.

    Nous n'inventons donc aucune vérification de signature ici.

    La confirmation doit toujours être validée avec :
    - event
    - reference
    - montant
    - état de la transaction
    - identifiant JessiKaPay
    """

    event = payload.event.strip().lower()

    # ========================================================
    # PAYMENT COMPLETED
    # ========================================================

    if event == "payment.completed":

        if payload.amount is None:
            raise HTTPException(
                status_code=400,
                detail="Montant manquant.",
            )

        request_id = (
            payload.request_id
            or payload.payment_request_id
        )

        if not request_id and not payload.reference:
            raise HTTPException(
                status_code=400,
                detail="Identifiant de paiement manquant.",
            )

        service = TransactionService(db)

        try:
            transaction = (
                await service.confirm_payment(
                    payment_reference=(
                        payload.reference
                    ),
                    request_id=request_id,
                    amount=payload.amount,
                )
            )

            return {
                "status": "accepted",
                "event": event,
                "transaction_id": transaction.id,
            }

        except TransactionServiceError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

    # ========================================================
    # CREDIT COMPLETED
    # ========================================================

    if event == "credit.completed":

        if payload.transaction_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "transaction_id manquant "
                    "dans credit.completed."
                ),
            )

        if payload.amount is None:
            raise HTTPException(
                status_code=400,
                detail="Montant manquant.",
            )

        # ----------------------------------------------------
        # 1. RETRAIT UTILISATEUR
        # ----------------------------------------------------

        withdrawal_service = WithdrawalService(db)

        try:
            withdrawal = (
                await withdrawal_service.confirm_payout(
                    transaction_id=(
                        str(payload.transaction_id)
                    ),
                    amount=payload.amount,
                    reference=payload.reference,
                )
            )

            return {
                "status": "accepted",
                "event": event,
                "type": "withdrawal",
                "withdrawal_id": withdrawal.id,
                "reference": withdrawal.reference,
            }

        except WithdrawalServiceError:
            # Ce n'est peut-être pas un retrait utilisateur.
            # On continue avec le payout vendeur.
            pass

        # ----------------------------------------------------
        # 2. PAYOUT VENDEUR D'UNE TRANSACTION
        # ----------------------------------------------------

        transaction_service = TransactionService(db)

        try:
            transaction = (
                await transaction_service.confirm_seller_payout(
                    provider_transaction_id=(
                        str(payload.transaction_id)
                    ),
                    amount=payload.amount,
                    reference=payload.reference,
                )
            )

            return {
                "status": "accepted",
                "event": event,
                "type": "seller_payout",
                "transaction_id": transaction.id,
            }

        except TransactionServiceError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

    # ========================================================
    # DEPOSIT COMPLETED
    # ========================================================

    if event == "deposit.completed":

        # Pour l'instant, on accuse réception uniquement.
        #
        # Le crédit automatique du portefeuille nécessitera
        # un modèle Deposit persistant avec une référence
        # idempotente.
        #
        # Aucun crédit direct n'est effectué ici afin d'éviter
        # un double crédit.

        return {
            "status": "accepted",
            "event": event,
            "message": (
                "Événement de dépôt reçu. "
                "Traitement du crédit wallet non activé "
                "dans cette version."
            ),
        }

    # ========================================================
    # UNKNOWN EVENT
    # ========================================================

    return {
        "status": "ignored",
        "event": event,
    }
