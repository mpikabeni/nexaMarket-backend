from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.deps import DBSession
from app.models.transaction import Transaction
from app.services.transaction_service import (
    TransactionService,
    TransactionServiceError,
)


router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


# ============================================================
# HELPERS
# ============================================================

def parse_timestamp(value):
    """
    Convertit le timestamp fourni par JessiKaPay en datetime
    lorsque possible.
    """

    if value is None:
        return None

    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(
                value,
                tz=timezone.utc,
            )

        value = str(value)

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        return datetime.fromisoformat(value)

    except (ValueError, TypeError, OverflowError):
        return None


async def find_transaction(
    db: DBSession,
    reference: str | None = None,
    request_id: str | None = None,
    provider_transaction_id: str | None = None,
):
    """
    Recherche une transaction NexMarket à partir des
    références JessiKaPay.
    """

    if reference:
        result = await db.execute(
            select(Transaction).where(
                Transaction.payment_reference
                == reference
            )
        )

        transaction = result.scalar_one_or_none()

        if transaction:
            return transaction

        # Une référence de payout peut également être
        # utilisée pour retrouver la transaction.
        result = await db.execute(
            select(Transaction).where(
                Transaction.seller_payout_reference
                == reference
            )
        )

        transaction = result.scalar_one_or_none()

        if transaction:
            return transaction

    if request_id:
        result = await db.execute(
            select(Transaction).where(
                Transaction.jessikapay_request_id
                == str(request_id)
            )
        )

        transaction = result.scalar_one_or_none()

        if transaction:
            return transaction

    if provider_transaction_id:
        result = await db.execute(
            select(Transaction).where(
                Transaction.jessikapay_payout_transaction_id
                == str(provider_transaction_id)
            )
        )

        transaction = result.scalar_one_or_none()

        if transaction:
            return transaction

    return None


# ============================================================
# JESSIKAPAY WEBHOOK
# ============================================================

@router.post(
    "/jessikapay",
    status_code=status.HTTP_200_OK,
)
async def jessikapay_webhook(
    request: Request,
    db: DBSession,
):
    """
    Reçoit les événements JessiKaPay.

    Événements pris en charge :

    - payment.completed
    - credit.completed
    - deposit.completed

    IMPORTANT :
    La documentation JessiKaPay fournie ne décrit pas de
    signature/authentification spécifique pour les webhooks.

    Nous n'inventons donc aucune vérification de signature.
    """

    try:
        payload = await request.json()

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload JSON invalide.",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload webhook invalide.",
        )

    event = str(
        payload.get("event", "")
    ).strip().lower()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Événement webhook absent.",
        )

    # --------------------------------------------------------
    # TIMESTAMP
    # --------------------------------------------------------

    event_timestamp = parse_timestamp(
        payload.get("timestamp")
    )

    # --------------------------------------------------------
    # PAYMENT COMPLETED
    # --------------------------------------------------------

    if event == "payment.completed":

        reference = payload.get(
            "reference"
        )

        request_id = payload.get(
            "request_id"
        )

        amount = payload.get(
            "amount"
        )

        transaction = await find_transaction(
            db=db,
            reference=reference,
            request_id=request_id,
        )

        if transaction is None:
            # On retourne 200 afin d'éviter une boucle
            # de livraison si JessiKaPay renvoie l'événement.
            return {
                "status": "ignored",
                "event": event,
                "reason": "transaction_not_found",
            }

        # ----------------------------------------------------
        # Vérification du montant
        # ----------------------------------------------------

        if amount is not None:

            try:
                webhook_amount = int(
                    float(amount)
                )

                expected_amount = int(
                    transaction.total_buyer_amount
                )

            except (
                TypeError,
                ValueError,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Montant webhook invalide.",
                )

            if webhook_amount != expected_amount:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Le montant du webhook ne correspond "
                        "pas au montant de la transaction."
                    ),
                )

        # ----------------------------------------------------
        # Idempotence
        # ----------------------------------------------------

        if transaction.payment_status == "completed":
            return {
                "status": "already_processed",
                "event": event,
                "transaction_id": transaction.id,
            }

        service = TransactionService(db)

        try:
            updated_transaction = (
                await service.confirm_payment(
                    transaction_id=transaction.id,
                    provider_status={
                        "status": "completed",
                        "event": event,
                        "request_id": request_id,
                        "reference": reference,
                        "amount": amount,
                    },
                )
            )

        except TransactionServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return {
            "status": "processed",
            "event": event,
            "transaction_id": (
                updated_transaction.id
            ),
            "transaction_status": (
                updated_transaction.status
            ),
            "payment_status": (
                updated_transaction.payment_status
            ),
            "processed_at": event_timestamp,
        }

    # --------------------------------------------------------
    # CREDIT COMPLETED
    # --------------------------------------------------------

    if event == "credit.completed":

        provider_transaction_id = (
            payload.get("transaction_id")
        )

        reference = payload.get(
            "reference"
        )

        jp_number = payload.get(
            "jp_number"
        )

        amount = payload.get(
            "amount"
        )

        transaction = await find_transaction(
            db=db,
            reference=reference,
            provider_transaction_id=(
                provider_transaction_id
            ),
        )

        if transaction is None:
            return {
                "status": "ignored",
                "event": event,
                "reason": "transaction_not_found",
            }

        # ----------------------------------------------------
        # Vérification du montant vendeur
        # ----------------------------------------------------

        if amount is not None:

            try:
                webhook_amount = int(
                    float(amount)
                )

                expected_amount = int(
                    transaction.seller_amount
                )

            except (
                TypeError,
                ValueError,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Montant webhook invalide.",
                )

            if webhook_amount != expected_amount:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Le montant du crédit ne correspond "
                        "pas au montant vendeur."
                    ),
                )

        # ----------------------------------------------------
        # Idempotence
        # ----------------------------------------------------

        if transaction.seller_paid_at is not None:
            return {
                "status": "already_processed",
                "event": event,
                "transaction_id": transaction.id,
            }

        if not provider_transaction_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "transaction_id JessiKaPay "
                    "manquant."
                ),
            )

        service = TransactionService(db)

        try:
            updated_transaction = (
                await service.confirm_seller_payout(
                    transaction_id=transaction.id,
                    provider_transaction_id=(
                        str(provider_transaction_id)
                    ),
                )
            )

        except TransactionServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return {
            "status": "processed",
            "event": event,
            "transaction_id": (
                updated_transaction.id
            ),
            "seller_paid": (
                updated_transaction.seller_paid_at
                is not None
            ),
            "jessikapay_transaction_id": (
                updated_transaction
                .jessikapay_payout_transaction_id
            ),
            "jp_number": jp_number,
            "processed_at": event_timestamp,
        }

    # --------------------------------------------------------
    # DEPOSIT COMPLETED
    # --------------------------------------------------------

    if event == "deposit.completed":

        request_id = payload.get(
            "request_id"
        )

        reference = payload.get(
            "reference"
        )

        amount = payload.get(
            "amount"
        )

        telegram_id = payload.get(
            "telegram_id"
        )

        # ----------------------------------------------------
        # Les dépôts NexMarket seront traités par le service
        # de dépôt lorsque la route deposits.py sera ajoutée.
        #
        # Pour l'instant, nous accusons réception de
        # l'événement sans créditer arbitrairement un wallet.
        # ----------------------------------------------------

        return {
            "status": "received",
            "event": event,
            "request_id": request_id,
            "reference": reference,
            "amount": amount,
            "telegram_id": telegram_id,
            "processed_at": event_timestamp,
        }

    # --------------------------------------------------------
    # EVENT INCONNU
    # --------------------------------------------------------

    return {
        "status": "ignored",
        "event": event,
        "reason": "unsupported_event",
    }
