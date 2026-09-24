# backend/app/routes/transactions.py

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models.channel import Channel
from app.models.listings import Listing
from app.models.platform import PlatformLedger, PlatformWallet
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet, WalletOperation
from app.schemas import (
    AdminTransactionAction,
    TransactionCreate,
    TransactionResponse,
)


router = APIRouter(
    prefix="/transactions",
    tags=["Transactions"],
)


# =========================================================
# HELPERS
# =========================================================

def generate_reference() -> str:
    """
    Génère une référence unique NexMarket.
    Exemple : NXM-TX-8A31F4C92B10
    """
    return f"NXM-TX-{uuid4().hex[:12].upper()}"


def generate_wallet_reference(prefix: str = "TX") -> str:
    """
    Référence unique pour les mouvements du wallet.
    """
    return f"NXM-{prefix}-{uuid4().hex[:16].upper()}"


def transaction_to_dict(transaction: Transaction) -> dict:
    """
    Convertit une transaction SQLAlchemy
    en dictionnaire compatible avec le frontend.
    """

    return {
        "id": transaction.id,
        "reference": transaction.reference,

        "listing_id": transaction.listing_id,

        "buyer_id": transaction.buyer_id,
        "seller_id": transaction.seller_id,

        "assigned_admin_id": transaction.assigned_admin_id,

        "channel_price": transaction.channel_price,
        "platform_fee": transaction.platform_fee,
        "provider_fee": transaction.provider_fee,

        "total_buyer_amount": transaction.total_buyer_amount,
        "seller_amount": transaction.seller_amount,

        "currency": transaction.currency,

        "status": transaction.status,

        "payment_provider": transaction.payment_provider,
        "payment_reference": transaction.payment_reference,
        "payment_status": transaction.payment_status,

        "telegram_chat_id": transaction.telegram_chat_id,

        "transfer_started_at": transaction.transfer_started_at,
        "transfer_completed_at": transaction.transfer_completed_at,

        "admin_note": transaction.admin_note,
        "cancellation_reason": transaction.cancellation_reason,
        "dispute_reason": transaction.dispute_reason,

        "created_at": transaction.created_at,
        "payment_confirmed_at": transaction.payment_confirmed_at,
        "assigned_at": transaction.assigned_at,
        "completed_at": transaction.completed_at,
        "cancelled_at": transaction.cancelled_at,
        "updated_at": transaction.updated_at,
    }


def get_transaction_for_user(
    db: Session,
    transaction_id: int,
    user: User,
) -> Transaction:

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    if (
        transaction.buyer_id != user.id
        and transaction.seller_id != user.id
        and not user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette transaction.",
        )

    return transaction


def get_or_create_wallet(
    db: Session,
    user_id: int,
    currency: str,
) -> Wallet:

    wallet = (
        db.query(Wallet)
        .filter(Wallet.user_id == user_id)
        .with_for_update()
        .first()
    )

    if wallet:
        return wallet

    wallet = Wallet(
        user_id=user_id,
        available_balance=Decimal("0.00"),
        blocked_balance=Decimal("0.00"),
        total_revenue=Decimal("0.00"),
        currency=currency,
    )

    db.add(wallet)
    db.flush()

    return wallet


def create_wallet_operation(
    db: Session,
    wallet: Wallet,
    operation_type: str,
    amount: Decimal,
    currency: str,
    reference: str,
    description: str,
    status_value: str = "completed",
) -> WalletOperation:

    operation = WalletOperation(
        wallet_id=wallet.id,
        operation_type=operation_type,
        amount=amount,
        currency=currency,
        status=status_value,
        reference=reference,
        description=description,
        completed_at=(
            datetime.utcnow()
            if status_value == "completed"
            else None
        ),
    )

    db.add(operation)

    return operation


def get_or_create_platform_wallet(
    db: Session,
    currency: str,
) -> PlatformWallet:

    platform_wallet = (
        db.query(PlatformWallet)
        .with_for_update()
        .first()
    )

    if platform_wallet:
        return platform_wallet

    platform_wallet = PlatformWallet(
        balance=Decimal("0.00"),
        currency=currency,
    )

    db.add(platform_wallet)
    db.flush()

    return platform_wallet


# =========================================================
# CREATE PURCHASE
# =========================================================

@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    # -----------------------------------------------------
    # Vérifier l'annonce avec verrouillage SQL
    # -----------------------------------------------------

    listing = (
        db.query(Listing)
        .filter(Listing.id == payload.listing_id)
        .with_for_update()
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    # -----------------------------------------------------
    # Une annonce doit être disponible
    # -----------------------------------------------------

    if listing.status != "available":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette annonce n'est plus disponible.",
        )

    # -----------------------------------------------------
    # Le vendeur ne peut pas acheter son propre canal
    # -----------------------------------------------------

    if listing.seller_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas acheter votre propre canal.",
        )

    # -----------------------------------------------------
    # Vérifier le canal
    # -----------------------------------------------------

    channel = (
        db.query(Channel)
        .filter(Channel.id == listing.channel_id)
        .first()
    )

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal introuvable.",
        )

    if not channel.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce canal n'est plus actif.",
        )

    if not channel.telegram_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce canal n'est pas encore vérifié.",
        )

    if not channel.bot_is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le bot NexMarket doit être administrateur du canal.",
        )

    if not channel.seller_is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le vendeur doit toujours être administrateur du canal.",
        )

    # -----------------------------------------------------
    # PRIX VERROUILLÉ
    # -----------------------------------------------------

    price = Decimal(str(listing.price))

    # -----------------------------------------------------
    # COMMISSION NEXMARKET
    #
    # Le taux est configuré dans Render.
    # Exemple :
    # 0.05 = 5 %
    # -----------------------------------------------------

    fee_rate = Decimal(
        str(settings.NEXMARKET_FEE_RATE)
    )

    if fee_rate < Decimal("0"):
        fee_rate = Decimal("0")

    if fee_rate > Decimal("1"):
        fee_rate = Decimal("1")

    platform_fee = (
        price * fee_rate
    ).quantize(Decimal("0.01"))

    provider_fee = Decimal("0.00")

    # L'acheteur paie :
    # prix du canal + commission NexMarket
    total_buyer_amount = (
        price + platform_fee + provider_fee
    ).quantize(Decimal("0.01"))

    # Le vendeur reçoit le prix du canal.
    seller_amount = price

    currency = listing.currency or settings.DEFAULT_CURRENCY

    # -----------------------------------------------------
    # WALLET ACHETEUR
    # -----------------------------------------------------

    buyer_wallet = get_or_create_wallet(
        db=db,
        user_id=current_user.id,
        currency=currency,
    )

    if buyer_wallet.currency != currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La devise du portefeuille ne correspond pas à l'annonce.",
        )

    # -----------------------------------------------------
    # VÉRIFIER LE SOLDE
    # -----------------------------------------------------

    if (
        buyer_wallet.available_balance
        < total_buyer_amount
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Solde insuffisant. "
                f"Montant nécessaire : {total_buyer_amount} {currency}."
            ),
        )

    # -----------------------------------------------------
    # EMPÊCHER UNE DOUBLE TRANSACTION ACTIVE
    # -----------------------------------------------------

    existing_transaction = (
        db.query(Transaction)
        .filter(
            Transaction.listing_id == listing.id,
            Transaction.status.in_(
                [
                    "pending_payment",
                    "payment_confirmed",
                    "waiting_admin",
                    "assigned",
                    "transfer_pending",
                    "disputed",
                ]
            ),
        )
        .first()
    )

    if existing_transaction:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Une transaction est déjà en cours pour cette annonce.",
        )

    # -----------------------------------------------------
    # CRÉER LA TRANSACTION
    # -----------------------------------------------------

    transaction = Transaction(
        reference=generate_reference(),

        listing_id=listing.id,

        buyer_id=current_user.id,
        seller_id=listing.seller_id,

        channel_price=price,
        platform_fee=platform_fee,
        provider_fee=provider_fee,

        total_buyer_amount=total_buyer_amount,
        seller_amount=seller_amount,

        currency=currency,

        status="payment_confirmed",

        # Achat depuis le portefeuille NexMarket
        payment_provider="wallet",
        payment_reference=None,
        payment_status="paid",

        telegram_chat_id=channel.telegram_chat_id,

        payment_confirmed_at=datetime.utcnow(),
    )

    db.add(transaction)
    db.flush()

    # -----------------------------------------------------
    # BLOQUER LES FONDS DE L'ACHETEUR
    # -----------------------------------------------------

    buyer_wallet.available_balance -= total_buyer_amount
    buyer_wallet.blocked_balance += total_buyer_amount

    buyer_wallet.updated_at = datetime.utcnow()

    create_wallet_operation(
        db=db,
        wallet=buyer_wallet,
        operation_type="transaction_hold",
        amount=total_buyer_amount,
        currency=currency,
        reference=generate_wallet_reference("HOLD"),
        description=(
            f"Fonds bloqués pour l'achat "
            f"du canal - transaction {transaction.reference}"
        ),
    )

    # -----------------------------------------------------
    # VERROUILLER LE PRIX DE L'ANNONCE
    # -----------------------------------------------------

    listing.status = "reserved"
    listing.locked_price = price
    listing.locked_at = datetime.utcnow()
    listing.updated_at = datetime.utcnow()

    # -----------------------------------------------------
    # LA TRANSACTION ATTEND UN ADMIN
    # -----------------------------------------------------

    transaction.status = "waiting_admin"
    transaction.payment_status = "paid"
    transaction.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(transaction)

    return transaction_to_dict(transaction)


# =========================================================
# LIST MY TRANSACTIONS
# =========================================================

@router.get(
    "",
    response_model=list[TransactionResponse],
)
def list_my_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    transactions = (
        db.query(Transaction)
        .filter(
            (
                (Transaction.buyer_id == current_user.id)
                | (Transaction.seller_id == current_user.id)
            )
        )
        .order_by(
            Transaction.created_at.desc()
        )
        .all()
    )

    return [
        transaction_to_dict(transaction)
        for transaction in transactions
    ]


# =========================================================
# ADMIN - LIST ALL
# =========================================================

@router.get(
    "/admin/all",
    response_model=list[TransactionResponse],
)
def list_all_transactions(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    transactions = (
        db.query(Transaction)
        .order_by(
            Transaction.created_at.desc()
        )
        .all()
    )

    return [
        transaction_to_dict(transaction)
        for transaction in transactions
    ]


# =========================================================
# GET ONE TRANSACTION
# =========================================================

@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
)
def get_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    transaction = get_transaction_for_user(
        db=db,
        transaction_id=transaction_id,
        user=current_user,
    )

    return transaction_to_dict(transaction)


# =========================================================
# ADMIN - TAKE CHARGE
# =========================================================

@router.post(
    "/{transaction_id}/assign",
    response_model=TransactionResponse,
)
def assign_transaction(
    transaction_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    if transaction.status not in {
        "waiting_admin",
        "assigned",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cette transaction ne peut pas "
                "être prise en charge maintenant."
            ),
        )

    # -----------------------------------------------------
    # Si déjà attribuée à un autre admin
    # -----------------------------------------------------

    if (
        transaction.assigned_admin_id
        and transaction.assigned_admin_id != admin.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette transaction est déjà prise en charge par un autre administrateur.",
        )

    transaction.assigned_admin_id = admin.id
    transaction.assigned_at = datetime.utcnow()
    transaction.status = "assigned"
    transaction.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(transaction)

    return transaction_to_dict(transaction)


# =========================================================
# ADMIN - START TELEGRAM TRANSFER
# =========================================================

@router.post(
    "/{transaction_id}/start-transfer",
    response_model=TransactionResponse,
)
def start_transfer(
    transaction_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    if transaction.assigned_admin_id != admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette transaction n'est pas assignée à cet administrateur.",
        )

    if transaction.status != "assigned":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La transaction n'est pas prête pour le transfert.",
        )

    listing = (
        db.query(Listing)
        .filter(Listing.id == transaction.listing_id)
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    channel = (
        db.query(Channel)
        .filter(Channel.id == listing.channel_id)
        .first()
    )

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal introuvable.",
        )

    # -----------------------------------------------------
    # Revalidation avant transfert
    # -----------------------------------------------------

    if not channel.telegram_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le canal n'est plus vérifié.",
        )

    if not channel.bot_is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le bot NexMarket n'est plus administrateur du canal.",
        )

    if not channel.seller_is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le vendeur n'est plus administrateur du canal.",
        )

    transaction.status = "transfer_pending"
    transaction.transfer_started_at = datetime.utcnow()
    transaction.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(transaction)

    return transaction_to_dict(transaction)


# =========================================================
# ADMIN - COMPLETE TRANSACTION
# =========================================================

@router.post(
    "/{transaction_id}/complete",
    response_model=TransactionResponse,
)
def complete_transaction(
    transaction_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    if transaction.assigned_admin_id != admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette transaction n'est pas assignée à cet administrateur.",
        )

    if transaction.status != "transfer_pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le transfert Telegram n'est pas en cours.",
        )

    # -----------------------------------------------------
    # Verrouiller le vendeur
    # -----------------------------------------------------

    seller_wallet = (
        db.query(Wallet)
        .filter(Wallet.user_id == transaction.seller_id)
        .with_for_update()
        .first()
    )

    if not seller_wallet:

        seller_wallet = Wallet(
            user_id=transaction.seller_id,
            available_balance=Decimal("0.00"),
            blocked_balance=Decimal("0.00"),
            total_revenue=Decimal("0.00"),
            currency=transaction.currency,
        )

        db.add(seller_wallet)
        db.flush()

    # -----------------------------------------------------
    # Verrouiller le wallet acheteur
    # -----------------------------------------------------

    buyer_wallet = (
        db.query(Wallet)
        .filter(Wallet.user_id == transaction.buyer_id)
        .with_for_update()
        .first()
    )

    if not buyer_wallet:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Portefeuille acheteur introuvable.",
        )

    total_locked = Decimal(
        str(transaction.total_buyer_amount)
    )

    seller_amount = Decimal(
        str(transaction.seller_amount)
    )

    platform_fee = Decimal(
        str(transaction.platform_fee)
    )

    # -----------------------------------------------------
    # Vérification anti-double exécution
    # -----------------------------------------------------

    if transaction.status == "completed":
        return transaction_to_dict(transaction)

    if buyer_wallet.blocked_balance < total_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Les fonds bloqués de l'acheteur sont insuffisants.",
        )

    # -----------------------------------------------------
    # CONSOMMER LES FONDS BLOQUÉS
    #
    # Ils ne retournent PAS dans le solde disponible
    # de l'acheteur.
    # -----------------------------------------------------

    buyer_wallet.blocked_balance -= total_locked
    buyer_wallet.updated_at = datetime.utcnow()

    create_wallet_operation(
        db=db,
        wallet=buyer_wallet,
        operation_type="transaction_release",
        amount=total_locked,
        currency=transaction.currency,
        reference=generate_wallet_reference("RELEASE"),
        description=(
            f"Déblocage final de la transaction "
            f"{transaction.reference}"
        ),
    )

    # -----------------------------------------------------
    # CRÉDITER LE VENDEUR
    # -----------------------------------------------------

    seller_wallet.available_balance += seller_amount
    seller_wallet.total_revenue += seller_amount
    seller_wallet.updated_at = datetime.utcnow()

    create_wallet_operation(
        db=db,
        wallet=seller_wallet,
        operation_type="sale_revenue",
        amount=seller_amount,
        currency=transaction.currency,
        reference=generate_wallet_reference("SALE"),
        description=(
            f"Revenu de vente pour "
            f"{transaction.reference}"
        ),
    )

    # -----------------------------------------------------
    # CRÉDITER LE PORTEFEUILLE NEXMARKET
    # -----------------------------------------------------

    if platform_fee > Decimal("0.00"):

        platform_wallet = get_or_create_platform_wallet(
            db=db,
            currency=transaction.currency,
        )

        platform_wallet.balance += platform_fee
        platform_wallet.updated_at = datetime.utcnow()

        ledger = PlatformLedger(
            reference=generate_wallet_reference("FEE"),
            operation_type="transaction_commission",
            amount=platform_fee,
            currency=transaction.currency,
            direction="credit",
            description=(
                f"Commission NexMarket - "
                f"{transaction.reference}"
            ),
            transaction_id=transaction.id,
        )

        db.add(ledger)

    # -----------------------------------------------------
    # MARQUER L'ANNONCE COMME VENDUE
    # -----------------------------------------------------

    listing = (
        db.query(Listing)
        .filter(Listing.id == transaction.listing_id)
        .with_for_update()
        .first()
    )

    if listing:
        listing.status = "sold"
        listing.locked_price = transaction.channel_price
        listing.updated_at = datetime.utcnow()

    # -----------------------------------------------------
    # TERMINER LA TRANSACTION
    # -----------------------------------------------------

    transaction.status = "completed"
    transaction.payment_status = "paid"
    transaction.transfer_completed_at = datetime.utcnow()
    transaction.completed_at = datetime.utcnow()
    transaction.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(transaction)

    return transaction_to_dict(transaction)


# =========================================================
# CANCEL TRANSACTION
# =========================================================

@router.post(
    "/{transaction_id}/cancel",
    response_model=TransactionResponse,
)
def cancel_transaction(
    transaction_id: int,
    payload: AdminTransactionAction,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    is_admin = current_user.is_admin

    is_participant = (
        transaction.buyer_id == current_user.id
        or transaction.seller_id == current_user.id
    )

    if not is_admin and not is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette transaction.",
        )

    if transaction.status in {
        "completed",
        "cancelled",
        "refunded",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette transaction est déjà terminée.",
        )

    # -----------------------------------------------------
    # Empêcher une annulation sauvage après transfert
    # -----------------------------------------------------

    if (
        transaction.status == "transfer_pending"
        and not is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Une transaction en transfert doit être traitée par un administrateur.",
        )

    # -----------------------------------------------------
    # Rembourser les fonds bloqués
    # -----------------------------------------------------

    buyer_wallet = (
        db.query(Wallet)
        .filter(Wallet.user_id == transaction.buyer_id)
        .with_for_update()
        .first()
    )

    if buyer_wallet:

        locked_amount = Decimal(
            str(transaction.total_buyer_amount)
        )

        if buyer_wallet.blocked_balance >= locked_amount:

            buyer_wallet.blocked_balance -= locked_amount
            buyer_wallet.available_balance += locked_amount
            buyer_wallet.updated_at = datetime.utcnow()

            create_wallet_operation(
                db=db,
                wallet=buyer_wallet,
                operation_type="refund",
                amount=locked_amount,
                currency=transaction.currency,
                reference=generate_wallet_reference("REFUND"),
                description=(
                    f"Remboursement de la transaction "
                    f"{transaction.reference}"
                ),
            )

    # -----------------------------------------------------
    # Libérer l'annonce
    # -----------------------------------------------------

    listing = (
        db.query(Listing)
        .filter(Listing.id == transaction.listing_id)
        .with_for_update()
        .first()
    )

    if listing and listing.status == "reserved":

        listing.status = "available"
        listing.locked_price = None
        listing.locked_at = None
        listing.updated_at = datetime.utcnow()

    # -----------------------------------------------------
    # Annuler
    # -----------------------------------------------------

    transaction.status = "cancelled"
    transaction.payment_status = "refunded"
    transaction.cancellation_reason = (
        payload.note or "Transaction annulée."
    )
    transaction.cancelled_at = datetime.utcnow()
    transaction.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(transaction)

    return transaction_to_dict(transaction)


# =========================================================
# OPEN DISPUTE
# =========================================================

@router.post(
    "/{transaction_id}/dispute",
    response_model=TransactionResponse,
)
def dispute_transaction(
    transaction_id: int,
    payload: AdminTransactionAction,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    is_admin = current_user.is_admin

    is_participant = (
        transaction.buyer_id == current_user.id
        or transaction.seller_id == current_user.id
    )

    if not is_admin and not is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette transaction.",
        )

    if transaction.status in {
        "completed",
        "cancelled",
        "refunded",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette transaction ne peut plus être contestée.",
        )

    transaction.status = "disputed"

    transaction.dispute_reason = (
        payload.note
        or "Litige ouvert."
    )

    transaction.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(transaction)

    return transaction_to_dict(transaction)


# =========================================================
# ADMIN ACTION CENTRALISÉE
# =========================================================

@router.post(
    "/{transaction_id}/admin-action",
    response_model=TransactionResponse,
)
def admin_transaction_action(
    transaction_id: int,
    payload: AdminTransactionAction,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    action = payload.action.strip().lower()

    # -----------------------------------------------------
    # ASSIGN
    # -----------------------------------------------------

    if action == "assign":

        transaction = (
            db.query(Transaction)
            .filter(Transaction.id == transaction_id)
            .with_for_update()
            .first()
        )

        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction introuvable.",
            )

        if transaction.status not in {
            "waiting_admin",
            "assigned",
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cette transaction ne peut pas être assignée.",
            )

        if (
            transaction.assigned_admin_id
            and transaction.assigned_admin_id != admin.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cette transaction est déjà assignée à un autre administrateur.",
            )

        transaction.assigned_admin_id = admin.id
        transaction.assigned_at = datetime.utcnow()
        transaction.status = "assigned"
        transaction.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(transaction)

        return transaction_to_dict(transaction)

    # -----------------------------------------------------
    # START TRANSFER
    # -----------------------------------------------------

    if action == "transfer":

        transaction = (
            db.query(Transaction)
            .filter(Transaction.id == transaction_id)
            .with_for_update()
            .first()
        )

        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction introuvable.",
            )

        if transaction.assigned_admin_id != admin.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Transaction non assignée à cet administrateur.",
            )

        if transaction.status != "assigned":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La transaction n'est pas prête pour le transfert.",
            )

        transaction.status = "transfer_pending"
        transaction.transfer_started_at = datetime.utcnow()
        transaction.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(transaction)

        return transaction_to_dict(transaction)

    # -----------------------------------------------------
    # COMPLETE
    # -----------------------------------------------------

    if action == "complete":

        return complete_transaction(
            transaction_id=transaction_id,
            admin=admin,
            db=db,
        )

    # -----------------------------------------------------
    # CANCEL
    # -----------------------------------------------------

    if action == "cancel":

        return cancel_transaction(
            transaction_id=transaction_id,
            payload=payload,
            current_user=admin,
            db=db,
        )

    # -----------------------------------------------------
    # DISPUTE
    # -----------------------------------------------------

    if action == "dispute":

        return dispute_transaction(
            transaction_id=transaction_id,
            payload=payload,
            current_user=admin,
            db=db,
        )

    # -----------------------------------------------------
    # REFUND
    # -----------------------------------------------------

    if action == "refund":

        return cancel_transaction(
            transaction_id=transaction_id,
            payload=AdminTransactionAction(
                action="refund",
                note=payload.note or "Remboursement administrateur.",
            ),
            current_user=admin,
            db=db,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Action inconnue. "
            "Actions disponibles : "
            "assign, transfer, complete, cancel, dispute, refund."
        ),
    )
