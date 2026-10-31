import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.channel import Channel
from app.models.schemas import ChannelCreate
from app.services.telegram_service import (
    get_telegram_service,
    TelegramService,
    TelegramServiceError,
)


router = APIRouter(
    prefix="/channels",
    tags=["Channels"],
)


# ============================================================
# HELPERS
# ============================================================

def serialize_channel(
    channel: Channel,
    include_private: bool = False,
):
    """
    Sérialise une chaîne.

    Les informations privées du propriétaire ne sont
    jamais retournées dans la réponse publique.
    """

    data = {
        "id": channel.id,
        "telegram_username": channel.telegram_username,
        "title": channel.title,
        "photo_url": channel.photo_url,
        "description": channel.description,
        "subscriber_count": channel.subscriber_count,
        "bot_is_admin": channel.bot_is_admin,
        "bot_permissions_verified": (
            channel.bot_permissions_verified
        ),
        "owner_verified": channel.owner_verified,
        "verification_status": (
            channel.verification_status
        ),
        "verified_at": channel.verified_at,
        "is_active": channel.is_active,
        "is_listed": channel.is_listed,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }

    if include_private:
        data.update(
            {
                "telegram_channel_id": (
                    channel.telegram_channel_id
                ),
                "owner_id": channel.owner_id,
                "owner_telegram_id": (
                    channel.owner_telegram_id
                ),
                "verified_by_admin_id": (
                    channel.verified_by_admin_id
                ),
                "rejection_reason": (
                    channel.rejection_reason
                ),
            }
        )

    return data


USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def normalize_username(raw: str) -> str:
    """Accepte @nom, nom, t.me/nom ou https://t.me/nom."""

    value = (raw or "").strip()

    value = re.sub(r"^https?://", "", value, flags=re.I)
    value = re.sub(r"^(www\.)?(t|telegram)\.me/", "", value, flags=re.I)
    value = value.split("?")[0].strip("/").lstrip("@")

    if not USERNAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Username de canal invalide. Exemple : @moncanal "
                "(canal public requis)."
            ),
        )

    return value


# ============================================================
# SUBMIT CHANNEL
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def submit_channel(
    payload: ChannelCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Soumet une chaîne Telegram à NexMarket.

    Le backend vérifie :
    - que la chaîne existe ;
    - que le bot NexMarket est administrateur ;
    - que le bot possède les permissions nécessaires ;
    - que l'utilisateur connecté est réellement OWNER ;
    """

    telegram_service = get_telegram_service()

    # --------------------------------------------------------
    # Résoudre l'identifiant numérique à partir du @username
    # (l'utilisateur ne connaît pas l'ID -100... de son canal)
    # --------------------------------------------------------

    channel_id = payload.telegram_channel_id

    if channel_id is None:
        username = normalize_username(
            payload.username or payload.telegram_username
        )

        try:
            chat = await telegram_service.get_channel(f"@{username}")
        except TelegramServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Canal introuvable. Vérifiez le @username et "
                    "ajoutez le bot NexMarket comme administrateur."
                ),
            ) from exc

        channel_id = chat.id

    # --------------------------------------------------------
    # Vérifier la chaîne Telegram
    # --------------------------------------------------------

    try:
        verification = (
            await telegram_service.verify_channel_submission(
                channel_id,
                current_user.telegram_id,
            )
        )
    except TelegramServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # verify_channel_submission AVALE les erreurs Telegram et renvoie
    # un objet vide avec `.error` : sans ce contrôle un canal non
    # vérifié (titre vide) était enregistré, ou plantait en base.
    if verification.error or not verification.title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                verification.error
                or "Impossible de vérifier ce canal Telegram."
            ),
        )

    if not verification.owner_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Seul le propriétaire du canal peut le mettre en vente."
            ),
        )

    # --------------------------------------------------------
    # Vérifier si la chaîne existe déjà
    # --------------------------------------------------------

    result = await db.execute(
        select(Channel).where(
            Channel.telegram_channel_id == channel_id
        )
    )

    existing_channel = result.scalar_one_or_none()

    if existing_channel is not None:

        # La chaîne appartient déjà à un autre compte.
        if (
            existing_channel.owner_id
            != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cette chaîne est déjà enregistrée "
                    "sur NexMarket."
                ),
            )

        # Une ancienne chaîne rejetée peut être resoumise.
        existing_channel.telegram_username = (
            verification.username
        )
        existing_channel.title = (
            verification.title
        )
        existing_channel.photo_url = (
            verification.photo_url
        )
        existing_channel.subscriber_count = (
            verification.subscriber_count
        )
        existing_channel.bot_is_admin = (
            verification.bot_is_admin
        )
        existing_channel.bot_permissions_verified = (
            verification.bot_permissions_verified
        )
        existing_channel.owner_verified = (
            verification.owner_verified
        )
        existing_channel.owner_telegram_id = (
            current_user.telegram_id
        )
        existing_channel.verification_status = (
            "submitted"
        )
        existing_channel.rejection_reason = None
        existing_channel.is_active = True
        existing_channel.updated_at = (
            datetime.now(timezone.utc)
        )

        if payload.description is not None:
            existing_channel.description = (
                payload.description
            )

        await db.commit()
        await db.refresh(existing_channel)

        return serialize_channel(
            existing_channel,
            include_private=False,
        )

    # --------------------------------------------------------
    # Nouvelle chaîne
    # --------------------------------------------------------

    channel = Channel(
        telegram_channel_id=channel_id,
        telegram_username=verification.username,
        title=verification.title,
        photo_url=verification.photo_url,
        description=(
            payload.description
            if payload.description is not None
            else None
        ),
        subscriber_count=(
            verification.subscriber_count
        ),
        owner_id=current_user.id,
        owner_telegram_id=current_user.telegram_id,
        bot_is_admin=verification.bot_is_admin,
        bot_permissions_verified=(
            verification.bot_permissions_verified
        ),
        owner_verified=verification.owner_verified,
        verification_status="submitted",
        is_active=True,
        is_listed=False,
    )

    db.add(channel)

    await db.commit()
    await db.refresh(channel)

    return serialize_channel(
        channel,
        include_private=False,
    )


# ============================================================
# MY CHANNELS
# ============================================================

@router.get("/mine")
async def get_my_channels(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les chaînes appartenant à l'utilisateur connecté.
    """

    result = await db.execute(
        select(Channel)
        .where(
            Channel.owner_id == current_user.id
        )
        .order_by(
            Channel.created_at.desc()
        )
    )

    channels = result.scalars().all()

    return {
        "channels": [
            serialize_channel(
                channel,
                include_private=False,
            )
            for channel in channels
        ],
        "count": len(channels),
    }


# ============================================================
# GET CHANNEL
# ============================================================

@router.get("/{channel_id}")
async def get_channel(
    channel_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les informations d'une chaîne.

    Le propriétaire peut consulter ses informations.
    Un administrateur peut consulter les informations privées.
    """

    result = await db.execute(
        select(Channel).where(
            Channel.id == channel_id
        )
    )

    channel = result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chaîne introuvable.",
        )

    is_owner = (
        channel.owner_id == current_user.id
    )

    if not is_owner and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé.",
        )

    return serialize_channel(
        channel,
        include_private=current_user.is_admin,
    )


# ============================================================
# VERIFY CHANNEL AGAIN
# ============================================================

@router.post("/{channel_id}/verify")
async def verify_channel(
    channel_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Relance la vérification Telegram d'une chaîne.

    Cette route est utile si le vendeur vient d'ajouter
    le bot comme administrateur ou a corrigé ses permissions.
    """

    result = await db.execute(
        select(Channel).where(
            Channel.id == channel_id
        )
    )

    channel = result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chaîne introuvable.",
        )

    if channel.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Seul le propriétaire de la chaîne "
                "peut lancer cette vérification."
            ),
        )

    telegram_service = get_telegram_service()

    try:
        verification = (
            await telegram_service.verify_channel_submission(
                channel.telegram_channel_id,
                current_user.telegram_id,
            )
        )

    except TelegramServiceError as exc:
        channel.bot_is_admin = False
        channel.bot_permissions_verified = False
        channel.owner_verified = False
        channel.verification_status = "rejected"
        channel.rejection_reason = str(exc)

        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


    # Même piège que pour la soumission : ne jamais écraser les données
    # du canal avec un résultat vide quand Telegram a renvoyé une erreur.
    if verification.error or not verification.title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                verification.error
                or "Impossible de vérifier ce canal Telegram."
            ),
        )

    channel.telegram_username = (
        verification.username
    )
    channel.title = verification.title
    channel.photo_url = verification.photo_url
    channel.subscriber_count = (
        verification.subscriber_count
    )
    channel.bot_is_admin = (
        verification.bot_is_admin
    )
    channel.bot_permissions_verified = (
        verification.bot_permissions_verified
    )
    channel.owner_verified = (
        verification.owner_verified
    )

    channel.verification_status = (
        "submitted"
    )

    channel.rejection_reason = None
    channel.updated_at = (
        datetime.now(timezone.utc)
    )

    await db.commit()
    await db.refresh(channel)

    return {
        "status": "success",
        "channel": serialize_channel(
            channel,
            include_private=False,
        ),
    }


# ============================================================
# REMOVE CHANNEL FROM SELLER ACCOUNT
# ============================================================

@router.delete("/{channel_id}")
async def remove_channel(
    channel_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Désactive une chaîne du compte du vendeur.

    La chaîne n'est pas supprimée physiquement de la base.
    """

    result = await db.execute(
        select(Channel).where(
            Channel.id == channel_id
        )
    )

    channel = result.scalar_one_or_none()

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chaîne introuvable.",
        )

    if channel.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette chaîne ne vous appartient pas.",
        )

    channel.is_active = False
    channel.is_listed = False

    # Une chaîne retirée ne doit plus pouvoir être vendue.
    if channel.verification_status == "approved":
        channel.verification_status = "suspended"

    channel.updated_at = (
        datetime.now(timezone.utc)
    )

    await db.commit()

    return {
        "status": "success",
        "channel_id": channel.id,
        "is_active": channel.is_active,
        "is_listed": channel.is_listed,
        "verification_status": (
            channel.verification_status
        ),
    }
