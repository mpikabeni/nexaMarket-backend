from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentAdmin, CurrentUser, DBSession
from app.models.schemas import TransactionCreate
from app.models.transaction import Transaction
from app.services.jessikapay_service import JessiKaPayService
from app.services.transaction_service import (
    TransactionService,
    TransactionServiceError,
)


router = APIRouter(
    prefix="/transactions",
    tags=["Transactions"],
)


def get_transaction_service(
    db: DBSession,
) -> TransactionService:
    return TransactionService(
        db=db,
        jessikapay=JessiKaPayService(),
    )


# ============================================================
# CREATE TRANSACTION
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction(
    payload: TransactionCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Crée une transaction pour acheter une annonce.
    """

    service = get_transaction_service(db)

    try:
        transaction = await service.create_transaction(
            buyer=current_user,
            listing_id=payload.listing_id,
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "id": transaction.id,
        "reference": transaction.reference,
        "listing_id": transaction.listing_id,
        "channel_price": transaction.channel_price,
        "platform_fee": transaction.platform_fee,
        "provider_fee": transaction.provider_fee,
        "total_buyer_amount": transaction.total_buyer_amount,
        "currency": transaction.currency,
        "seller_amount": transaction.seller_amount,
        "status": transaction.status,
        "payment_status": transaction.payment_status,
    }


# ============================================================
# MY TRANSACTIONS
# ============================================================

@router.get("/mine")
async def get_my_transactions(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les transactions dans lesquelles l'utilisateur
    est acheteur ou vendeur.
    """

    result = await db.execute(
        select(Transaction)
        .where(
            (
                Transaction.buyer_id
                == current_user.id
            )
            |
            (
                Transaction.seller_id
                == current_user.id
            )
        )
        .order_by(
            Transaction.created_at.desc()
        )
    )

    transactions = result.scalars().all()

    return {
        "transactions": [
            {
                "id": transaction.id,
                "reference": transaction.reference,
                "listing_id": transaction.listing_id,
                "channel_price": transaction.channel_price,
                "platform_fee": transaction.platform_fee,
                "provider_fee": transaction.provider_fee,
                "total_buyer_amount": (
                    transaction.total_buyer_amount
                ),
                "seller_amount": transaction.seller_amount,
                "currency": transaction.currency,
                "status": transaction.status,
                "payment_status": (
                    transaction.payment_status
                ),
                "escrow_held": (
                    transaction.escrow_held
                ),
                "protection_ends_at": (
                    transaction.protection_ends_at
                ),
                "created_at": transaction.created_at,
            }
            for transaction in transactions
        ]
    }


# ============================================================
# TRANSACTION DETAILS
# ============================================================

@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les détails d'une transaction uniquement
    à l'acheteur, au vendeur ou à un administrateur.
    """

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable.",
        )

    if (
        transaction.buyer_id != current_user.id
        and transaction.seller_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="Accès non autorisé.",
        )

    return {
        "id": transaction.id,
        "reference": transaction.reference,
        "listing_id": transaction.listing_id,
        "channel_price": transaction.channel_price,
        "platform_fee": transaction.platform_fee,
        "provider_fee": transaction.provider_fee,
        "total_buyer_amount": (
            transaction.total_buyer_amount
        ),
        "seller_amount": transaction.seller_amount,
        "currency": transaction.currency,
        "platform_fee_rate": (
            transaction.platform_fee_rate
        ),
        "status": transaction.status,
        "payment_provider": (
            transaction.payment_provider
        ),
        "payment_status": (
            transaction.payment_status
        ),
        "escrow_held": transaction.escrow_held,
        "escrow_held_at": transaction.escrow_held_at,
        "protection_ends_at": (
            transaction.protection_ends_at
        ),
        "transfer_started_at": (
            transaction.transfer_started_at
        ),
        "transfer_completed_at": (
            transaction.transfer_completed_at
        ),
        "created_at": transaction.created_at,
    }


# ============================================================
# CREATE JESSIKAPAY PAYMENT
# ============================================================

@router.post(
    "/{transaction_id}/payment",
)
async def create_transaction_payment(
    transaction_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Génère le lien de paiement JessiKaPay.

    Seul l'acheteur peut lancer le paiement.
    """

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable.",
        )

    if transaction.buyer_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Seul l'acheteur peut effectuer le paiement.",
        )

    service = get_transaction_service(db)

    try:
        return await service.create_payment(
            transaction_id=transaction_id,
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


# ============================================================
# CHECK JESSIKAPAY PAYMENT
# ============================================================

@router.post(
    "/{transaction_id}/payment/check",
)
async def check_transaction_payment(
    transaction_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Vérifie directement le statut du paiement auprès
    de JessiKaPay.

    Cette route ne considère jamais la création du payment-link
    comme un paiement réussi.
    """

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable.",
        )

    if transaction.buyer_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Accès non autorisé.",
        )

    if not transaction.payment_reference:
        raise HTTPException(
            status_code=400,
            detail="Aucune demande de paiement n'existe.",
        )

    # La référence NexMarket est utilisée pour retrouver
    # la demande JessiKaPay uniquement si request_id est
    # disponible dans l'étape de création.
    #
    # Cette route attend donc le request_id côté transaction
    # dans une prochaine migration si nous voulons persister
    # explicitement cet identifiant fournisseur.
    raise HTTPException(
        status_code=501,
        detail=(
            "Le request_id JessiKaPay doit être enregistré "
            "dans le modèle Transaction avant d'activer "
            "la vérification directe par cette route."
        ),
    )


# ============================================================
# ADMIN : ASSIGN TRANSACTION
# ============================================================

@router.post(
    "/{transaction_id}/assign",
)
async def assign_transaction(
    transaction_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    service = get_transaction_service(db)

    try:
        transaction = await service.assign_admin(
            transaction_id=transaction_id,
            admin=current_admin,
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": "success",
        "transaction_id": transaction.id,
        "transaction_status": transaction.status,
    }


# ============================================================
# ADMIN : START TRANSFER
# ============================================================

@router.post(
    "/{transaction_id}/start-transfer",
)
async def start_transaction_transfer(
    transaction_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    service = get_transaction_service(db)

    try:
        transaction = await service.start_transfer(
            transaction_id=transaction_id,
            admin=current_admin,
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": "success",
        "transaction_id": transaction.id,
        "transaction_status": transaction.status,
        "transfer_started_at": (
            transaction.transfer_started_at
        ),
    }


# ============================================================
# ADMIN : COMPLETE TRANSFER
# ============================================================

@router.post(
    "/{transaction_id}/complete-transfer",
)
async def complete_transaction_transfer(
    transaction_id: int,
    current_admin: CurrentAdmin,
    db: DBSession,
):
    """
    L'admin confirme que le transfert du canal a été
    vérifié.

    Cela démarre la période de protection.
    """

    service = get_transaction_service(db)

    try:
        transaction = await service.complete_transfer(
            transaction_id=transaction_id,
            admin=current_admin,
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": "success",
        "transaction_id": transaction.id,
        "transaction_status": transaction.status,
        "protection_ends_at": (
            transaction.protection_ends_at
        ),
    }


# ============================================================
# FINISH PROTECTION
# ============================================================

@router.post(
    "/{transaction_id}/finish-protection",
)
async def finish_transaction_protection(
    transaction_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Termine la période de protection uniquement après
    son expiration.
    """

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable.",
        )

    if (
        transaction.buyer_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="Accès non autorisé.",
        )

    service = get_transaction_service(db)

    try:
        transaction = await service.finish_protection(
            transaction_id=transaction_id,
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": "success",
        "transaction_id": transaction.id,
        "transaction_status": transaction.status,
        "buyer_confirmed_at": (
            transaction.buyer_confirmed_at
        ),
    }


# ============================================================
# OPEN DISPUTE
# ============================================================

@router.post(
    "/{transaction_id}/dispute",
)
async def open_transaction_dispute(
    transaction_id: int,
    reason: str,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Permet à l'acheteur ou au vendeur d'ouvrir un litige.
    """

    if not reason.strip():
        raise HTTPException(
            status_code=400,
            detail="Le motif du litige est obligatoire.",
        )

    service = get_transaction_service(db)

    try:
        transaction = await service.open_dispute(
            transaction_id=transaction_id,
            user=current_user,
            reason=reason.strip(),
        )
    except TransactionServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "status": "success",
        "transaction_id": transaction.id,
        "transaction_status": transaction.status,
        "disputed_at": transaction.disputed_at,
    }
