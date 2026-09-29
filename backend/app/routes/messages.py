from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from datetime import datetime, timezone

from app.deps import CurrentUser, DBSession
from app.models.message import Message
from app.models.transaction import Transaction
from app.models.schemas import MessageCreate


router = APIRouter(
    prefix="/messages",
    tags=["Messages"],
)


# ============================================================
# HELPERS
# ============================================================

async def get_transaction(
    transaction_id: int,
    db: DBSession,
) -> Transaction:

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    return transaction


def can_access_transaction(
    transaction: Transaction,
    user,
) -> bool:

    if user.is_admin:
        return True

    if transaction.buyer_id == user.id:
        return True

    if transaction.seller_id == user.id:
        return True

    return False


# ============================================================
# GET TRANSACTION MESSAGES
# ============================================================

@router.get(
    "/transaction/{transaction_id}",
)
async def get_transaction_messages(
    transaction_id: int,
    current_user: CurrentUser,
    db: DBSession,
    limit: int = 100,
    before_id: int | None = None,
):
    """
    Retourne les messages du chat d'une transaction.

    Participants autorisés :
    - acheteur
    - vendeur
    - administrateur
    """

    transaction = await get_transaction(
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

    if limit < 1:
        limit = 1

    if limit > 100:
        limit = 100

    query = (
        select(Message)
        .where(
            Message.transaction_id
            == transaction_id
        )
    )

    if before_id is not None:
        query = query.where(
            Message.id < before_id
        )

    query = (
        query
        .order_by(Message.id.desc())
        .limit(limit)
    )

    result = await db.execute(query)

    messages = list(
        reversed(result.scalars().all())
    )

    return {
        "transaction_id": transaction.id,
        "messages": [
            {
                "id": message.id,
                "transaction_id": message.transaction_id,
                "sender_id": message.sender_id,
                "sender_role": message.sender_role,
                "content": message.content,
                "message_type": message.message_type,
                "attachment_url": message.attachment_url,
                "attachment_file_id": (
                    message.attachment_file_id
                ),
                "is_system_message": (
                    message.is_system_message
                ),
                "is_read": message.is_read,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


# ============================================================
# SEND MESSAGE
# ============================================================

@router.post(
    "/transaction/{transaction_id}",
    status_code=status.HTTP_201_CREATED,
)
async def send_transaction_message(
    transaction_id: int,
    payload: MessageCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Envoie un message dans le chat de la transaction.

    Le message est associé à la transaction et son auteur
    est déterminé côté serveur.
    """

    transaction = await get_transaction(
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

    # --------------------------------------------------------
    # Déterminer le rôle de l'expéditeur
    # --------------------------------------------------------

    if current_user.is_admin:
        sender_role = "admin"

    elif transaction.buyer_id == current_user.id:
        sender_role = "buyer"

    elif transaction.seller_id == current_user.id:
        sender_role = "seller"

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Expéditeur non autorisé.",
        )

    # --------------------------------------------------------
    # Validation du contenu
    # --------------------------------------------------------

    content = (
        payload.content.strip()
        if payload.content
        else ""
    )

    if not content and not payload.attachment_file_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le message ne peut pas être vide.",
        )

    if len(content) > 5000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le message ne peut pas dépasser "
                "5000 caractères."
            ),
        )

    # --------------------------------------------------------
    # Type de message
    # --------------------------------------------------------

    message_type = payload.message_type or "text"

    allowed_types = {
        "text",
        "image",
        "document",
    }

    if message_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type de message invalide.",
        )

    # --------------------------------------------------------
    # Création
    # --------------------------------------------------------

    message = Message(
        transaction_id=transaction.id,
        sender_id=current_user.id,
        sender_telegram_id=(
            current_user.telegram_id
        ),
        sender_role=sender_role,
        content=content or None,
        message_type=message_type,
        attachment_url=(
            payload.attachment_url
        ),
        attachment_file_id=(
            payload.attachment_file_id
        ),
        is_system_message=False,
        is_read=False,
    )

    db.add(message)

    await db.commit()
    await db.refresh(message)

    return {
        "id": message.id,
        "transaction_id": message.transaction_id,
        "sender_id": message.sender_id,
        "sender_role": message.sender_role,
        "content": message.content,
        "message_type": message.message_type,
        "attachment_url": message.attachment_url,
        "attachment_file_id": (
            message.attachment_file_id
        ),
        "is_system_message": (
            message.is_system_message
        ),
        "is_read": message.is_read,
        "created_at": message.created_at,
    }


# ============================================================
# MARK MESSAGES AS READ
# ============================================================

@router.post(
    "/transaction/{transaction_id}/read",
)
async def mark_transaction_messages_read(
    transaction_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Marque comme lus les messages envoyés par les autres
    participants de la transaction.
    """

    transaction = await get_transaction(
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

    result = await db.execute(
        select(Message).where(
            Message.transaction_id
            == transaction_id,
            Message.sender_id
            != current_user.id,
            Message.is_read.is_(False),
            Message.is_deleted.is_(False),
        )
    )

    messages = result.scalars().all()

    now = datetime.now(timezone.utc)

    for message in messages:
        message.is_read = True
        message.read_at = now

    await db.commit()

    return {
        "status": "success",
        "transaction_id": transaction_id,
        "messages_marked_as_read": len(messages),
    }


# ============================================================
# DELETE MESSAGE
# ============================================================

@router.delete(
    "/{message_id}",
)
async def delete_message(
    message_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Suppression logique d'un message.

    Le message n'est pas supprimé de la base de données.
    """

    result = await db.execute(
        select(Message).where(
            Message.id == message_id
        )
    )

    message = result.scalar_one_or_none()

    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message introuvable.",
        )

    transaction = await get_transaction(
        message.transaction_id,
        db,
    )

    # Seul l'auteur ou un admin peut supprimer
    # un message.
    if (
        message.sender_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas supprimer ce message.",
        )

    if message.is_deleted:
        return {
            "status": "already_deleted",
            "message_id": message.id,
        }

    message.is_deleted = True
    message.deleted_at = (
        datetime.now(timezone.utc)
    )
    message.deleted_by_admin_id = (
        current_user.id
        if current_user.is_admin
        else None
    )

    await db.commit()

    return {
        "status": "success",
        "message_id": message.id,
        "deleted": True,
    }
