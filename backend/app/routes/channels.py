from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, CurrentAdmin, DBSession
from app.models.channel import Channel
from app.models.schemas import ChannelCreate, ChannelResponse
from app.services.telegram_service import TelegramService


router = APIRouter(
    prefix="/channels",
    tags=["Channels"],
)


# ============================================================
# SUBMIT CHANNEL
# ============================================================

@router.post(
    "",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_channel(
    payload: ChannelCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Soumet un canal Telegram à NexMarket.

    Conditions :
    - le canal doit être accessible au bot ;
    - le bot doit être administrateur ;
    - le bot doit avoir les permissions nécessaires ;
    - l'utilisateur connecté doit être OWNER du canal.
    """

    # --------------------------------------------------------
    # Vérifier qu'il n'existe pas déjà
    # --------------------------------------------------------

    result = await db.execute(
        select(Channel).where(
            Channel.telegram_channel_id
            == payload.telegram_channel_id
        )
    )

    existing_channel = result.scalar_one_or_none()

    if existing_channel is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce canal est déjà enregistré sur NexMarket.",
        )

    # --------------------------------------------------------
    # Vérification Telegram
    # --------------------------------------------------------

    telegram = TelegramService()

    try:
        verification = (
            await telegram.verify_channel_submission(
                channel_id=payload.telegram_channel_id,
                submitted_by_telegram_id=current_user.telegram_id,
            )
        )
    finally:
        await telegram.close()

    if verification.error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=verification.error,
        )

    if not verification.bot_is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le bot NexMarket doit être administrateur "
                "du canal avant sa soumission."
            ),
        )

    if not verification.bot_permissions_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le bot NexMarket ne possède pas toutes les "
                "permissions administrateur nécessaires."
            ),
        )

    if not verification.owner_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Seul le propriétaire du canal Telegram "
                "peut soumettre ce canal."
            ),
        )

    # --------------------------------------------------------
    # Création du canal
    # --------------------------------------------------------

    channel = Channel(
        telegram_channel_id=verification.channel_id,
        telegram_username=verification.username,
        title=verification.title or payload.title,
        description=(
            payload.description
            or verification.title
        ),
        subscriber_count=verification.subscriber_count,
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

    return channel


# ============================================================
# MY CHANNELS
# ============================================================

@router.get(
    "/mine",
    response_model=list[ChannelResponse],
)
async def get_my_channels(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne uniquement les canaux appartenant
    à l'utilisateur connecté.
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

    return list(result.scalars().all())


# ============================================================
# CHANNEL DETAILS
# ============================================================

@router.get(
    "/{channel_id}",
    response_model=ChannelResponse,
)
async def get_channel(
    channel_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Un utilisateur ne peut consulter les détails privés
    d'un canal que s'il en est propriétaire ou administrateur.
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
            detail="Canal introuvable.",
        )

    if (
        channel.owner_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé.",
        )

    return channel


# ============================================================
# REFRESH TELEGRAM VERIFICATION
# ============================================================

@router.post(
    "/{channel_id}/verify",
    response_model=ChannelResponse,
)
async def refresh_channel_verification(
    channel_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Re-vérifie les droits Telegram du canal.

    Utile si le propriétaire ajoute le bot comme admin
    après avoir commencé la procédure.
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
            detail="Canal introuvable.",
        )

    if channel.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'êtes pas propriétaire de ce canal.",
        )

    telegram = TelegramService()

    try:
        verification = (
            await telegram.verify_channel_submission(
                channel_id=channel.telegram_channel_id,
                submitted_by_telegram_id=current_user.telegram_id,
            )
        )
    finally:
        await telegram.close()

    if verification.error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=verification.error,
        )

    channel.telegram_username = verification.username
    channel.title = (
        verification.title
        or channel.title
    )
    channel.subscriber_count = (
        verification.subscriber_count
    )

    channel.bot_is_admin = verification.bot_is_admin
    channel.bot_permissions_verified = (
        verification.bot_permissions_verified
    )
    channel.owner_verified = verification.owner_verified

    if (
        verification.bot_is_admin
        and verification.bot_permissions_verified
        and verification.owner_verified
    ):
        channel.verification_status = "submitted"
    else:
        channel.verification_status = "pending"

    await db.commit()
    await db.refresh(channel)

    return channel
