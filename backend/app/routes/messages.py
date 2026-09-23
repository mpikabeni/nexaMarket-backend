# ============================================================
# NEXMARKET
# backend/app/routes/messages.py
# ============================================================

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.message import Message
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas import MessageCreate, MessageResponse


router = APIRouter(
    prefix="/messages",
    tags=["Messages"],
)


# ============================================================
# HELPERS
# ============================================================

def get_transaction_or_404(
    transaction_id: int,
    db: Session,
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

    return transaction


def can_access_transaction(
    transaction: Transaction,
    user: User,
) -> bool:

    # Acheteur
    if transaction.buyer_id == user.id:
        return True

    # Vendeur
    if transaction.seller_id == user.id:
        return True

    # Administrateur de la plateforme
    if user.is_admin:
        return True

    # Administrateur assigné
    if transaction.assigned_admin_id == user.id:
        return True

    return False


# ============================================================
# LISTE DES MESSAGES D'UNE TRANSACTION
# ============================================================

@router.get(
    "/transaction/{transaction_id}",
    response_model=list[MessageResponse],
)
def get_transaction_messages(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    transaction = get_transaction_or_404(
        transaction_id,
        db,
    )

    if not can_access_transaction(
        transaction,
        current_user,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette conversation.",
        )

    messages = (
        db.query(Message)
        .filter(
            Message.transaction_id == transaction.id
        )
        .order_by(
            Message.created_at.asc(),
            Message.id.asc(),
        )
        .all()
    )

    return messages


# ============================================================
# ENVOYER UN MESSAGE
# ============================================================

@router.post(
    "",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    transaction = get_transaction_or_404(
        payload.transaction_id,
        db,
    )

    if not can_access_transaction(
        transaction,
        current_user,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette transaction.",
        )

    # Une transaction terminée ou annulée ne doit plus
    # accepter de nouveaux messages normaux.
    if transaction.status in {
        "completed",
        "cancelled",
        "refunded",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette transaction est terminée.",
        )

    message_type = (
        payload.message_type.strip().lower()
        if payload.message_type
        else "text"
    )

    allowed_types = {
        "text",
        "image",
        "document",
        "system",
    }

    if message_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Type de message invalide. "
                "Types autorisés : text, image, document, system."
            ),
        )

    # Un utilisateur normal ne peut pas créer
    # un message système.
    if message_type == "system" and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul un administrateur peut créer un message système.",
        )

    content = payload.content.strip()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le message ne peut pas être vide.",
        )

    message = Message(
        transaction_id=transaction.id,
        sender_id=current_user.id,
        content=content,
        message_type=message_type,
        media_url=payload.media_url,
        media_type=payload.media_type,
        is_system_message=(
            message_type == "system"
        ),
        is_read=False,
        created_at=datetime.utcnow(),
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


# ============================================================
# MARQUER LES MESSAGES COMME LUS
# ============================================================

@router.post(
    "/transaction/{transaction_id}/read",
)
def mark_transaction_messages_read(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    transaction = get_transaction_or_404(
        transaction_id,
        db,
    )

    if not can_access_transaction(
        transaction,
        current_user,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette conversation.",
        )

    updated = (
        db.query(Message)
        .filter(
            Message.transaction_id == transaction.id,
            Message.sender_id != current_user.id,
            Message.is_read.is_(False),
        )
        .update(
            {
                Message.is_read: True
            },
            synchronize_session=False,
        )
    )

    db.commit()

    return {
        "status": "success",
        "message": "Messages marqués comme lus.",
        "updated": updated,
    }


# ============================================================
# NOMBRE DE MESSAGES NON LUS
# ============================================================

@router.get(
    "/transaction/{transaction_id}/unread-count",
)
def get_unread_count(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    transaction = get_transaction_or_404(
        transaction_id,
        db,
    )

    if not can_access_transaction(
        transaction,
        current_user,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès à cette conversation.",
        )

    count = (
        db.query(Message)
        .filter(
            Message.transaction_id == transaction.id,
            Message.sender_id != current_user.id,
            Message.is_read.is_(False),
        )
        .count()
    )

    return {
        "transaction_id": transaction.id,
        "unread_count": count,
    }


# ============================================================
# SUPPRIMER UN MESSAGE
# ============================================================

@router.delete(
    "/{message_id}",
)
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    message = (
        db.query(Message)
        .filter(Message.id == message_id)
        .first()
    )

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message introuvable.",
        )

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == message.transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    # Seul l'auteur ou un admin peut supprimer.
    if (
        message.sender_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas supprimer ce message.",
        )

    db.delete(message)
    db.commit()

    return {
        "status": "success",
        "message": "Message supprimé.",
    }