# backend/app/routes/channels.py

from __future__ import annotations

from datetime import datetime

import fastapi
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.channel import Channel
from app.models.user import User
from app.services.telegram_service import (
    TelegramServiceError,
    telegram_service,
)


# ============================================================
# ROUTER
# ============================================================

router = fastapi.APIRouter(
    prefix="/channels",
    tags=["Channels"],
)


# ============================================================
# SCHEMAS
# ============================================================


class ChannelCreateRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    country: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    language: str = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )


class ChannelUpdateRequest(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=2,
        max_length=255,
    )

    category: str | None = Field(
        default=None,
        max_length=100,
    )

    country: str | None = Field(
        default=None,
        max_length=100,
    )

    language: str | None = Field(
        default=None,
        max_length=50,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )


# ============================================================
# OUTILS
# ============================================================


def channel_to_dict(channel: Channel) -> dict:
    return {
        "id": channel.id,
        "telegram_chat_id": channel.telegram_chat_id,
        "title": channel.title,
        "username": channel.username,
        "description": channel.description,
        "photo_url": channel.photo_url,
        "category": channel.category,
        "country": channel.country,
        "language": channel.language,
        "subscribers_count": channel.subscribers_count,
        "telegram_verified": channel.telegram_verified,
        "bot_is_admin": channel.bot_is_admin,
        "seller_is_admin": channel.seller_is_admin,
        "verification_note": channel.verification_note,
        "verified_at": (
            channel.verified_at.isoformat()
            if channel.verified_at
            else None
        ),
        "owner_id": channel.owner_id,
        "is_active": channel.is_active,
        "created_at": (
            channel.created_at.isoformat()
            if channel.created_at
            else None
        ),
        "updated_at": (
            channel.updated_at.isoformat()
            if channel.updated_at
            else None
        ),
    }


def clean_username(username: str) -> str:
    username = username.strip()

    if username.startswith("https://t.me/"):
        username = username.replace(
            "https://t.me/",
            "",
            1,
        )

    if username.startswith("http://t.me/"):
        username = username.replace(
            "http://t.me/",
            "",
            1,
        )

    if username.startswith("@"):
        username = username[1:]

    return username.strip()


# ============================================================
# MES CANAUX
# ============================================================


@router.get("/mine")
def my_channels(
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(get_current_user),
):
    """
    Retourne tous les canaux appartenant à l'utilisateur connecté.
    """

    channels = (
        db.query(Channel)
        .filter(
            Channel.owner_id == current_user.id,
            Channel.is_active.is_(True),
        )
        .order_by(Channel.created_at.desc())
        .all()
    )

    return {
        "status": "success",
        "count": len(channels),
        "channels": [
            channel_to_dict(channel)
            for channel in channels
        ],
    }


# ============================================================
# OBTENIR UN CANAL
# ============================================================


@router.get("/{channel_id}")
def get_channel(
    channel_id: int,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(get_current_user),
):
    channel = (
        db.query(Channel)
        .filter(
            Channel.id == channel_id,
            Channel.is_active.is_(True),
        )
        .first()
    )

    if not channel:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Canal introuvable.",
        )

    return {
        "status": "success",
        "channel": channel_to_dict(channel),
    }


# ============================================================
# AJOUTER UN CANAL
# ============================================================


@router.post("")
def create_channel(
    payload: ChannelCreateRequest,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(get_current_user),
):
    username = clean_username(payload.username)

    if not username:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Nom d'utilisateur Telegram invalide.",
        )

    # --------------------------------------------------------
    # Vérifie si le canal existe déjà dans NexMarket
    # --------------------------------------------------------

    existing = (
        db.query(Channel)
        .filter(
            Channel.username == username,
            Channel.is_active.is_(True),
        )
        .first()
    )

    if existing:
        raise fastapi.HTTPException(
            status_code=409,
            detail="Ce canal existe déjà sur NexMarket.",
        )

    # --------------------------------------------------------
    # Vérification Telegram
    # --------------------------------------------------------

    try:
        verification = telegram_service.verify_channel(
            username
        )
    except TelegramServiceError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise fastapi.HTTPException(
            status_code=502,
            detail="Impossible de vérifier le canal Telegram.",
        ) from exc

    if not verification:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Canal Telegram introuvable.",
        )

    # --------------------------------------------------------
    # Vérifie que le vendeur est administrateur
    # --------------------------------------------------------

    telegram_chat_id = verification.get(
        "chat_id"
    )

    if telegram_chat_id is None:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Identifiant Telegram du canal introuvable.",
        )

    try:
        seller_is_admin = telegram_service.verify_user_admin(
            telegram_chat_id,
            current_user.telegram_id,
        )
    except TelegramServiceError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception:
        seller_is_admin = False

    if not seller_is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail=(
                "Tu dois être administrateur du canal "
                "pour l'ajouter à NexMarket."
            ),
        )

    # --------------------------------------------------------
    # Vérifie que le bot NexMarket est administrateur
    # --------------------------------------------------------

    try:
        bot_is_admin = telegram_service.verify_bot_admin(
            telegram_chat_id
        )
    except TelegramServiceError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception:
        bot_is_admin = False

    if not bot_is_admin:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                "Le bot NexMarket doit être ajouté comme "
                "administrateur du canal avant sa vérification."
            ),
        )

    # --------------------------------------------------------
    # Informations Telegram
    # --------------------------------------------------------

    title = verification.get(
        "title"
    ) or username

    description = (
        payload.description
        if payload.description is not None
        else verification.get("description")
    )

    subscribers_count = verification.get(
        "subscribers_count",
        0,
    )

    try:
        subscribers_count = int(
            subscribers_count or 0
        )
    except (TypeError, ValueError):
        subscribers_count = 0

    photo_url = verification.get(
        "photo_url"
    )

    # --------------------------------------------------------
    # Création du canal
    # --------------------------------------------------------

    channel = Channel(
        telegram_chat_id=int(telegram_chat_id),
        title=title,
        username=username,
        description=description,
        photo_url=photo_url,
        category=payload.category,
        country=payload.country,
        language=payload.language,
        subscribers_count=subscribers_count,
        telegram_verified=True,
        bot_is_admin=True,
        seller_is_admin=True,
        verification_note=(
            "Canal Telegram vérifié. "
            "Le bot NexMarket et le vendeur sont administrateurs."
        ),
        verified_at=datetime.utcnow(),
        owner_id=current_user.id,
        is_active=True,
    )

    db.add(channel)
    db.commit()
    db.refresh(channel)

    return {
        "status": "success",
        "message": (
            "Canal ajouté et vérifié avec succès."
        ),
        "channel": channel_to_dict(channel),
    }


# ============================================================
# REVÉRIFIER UN CANAL
# ============================================================


@router.post("/{channel_id}/verify")
def verify_channel(
    channel_id: int,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(get_current_user),
):
    channel = (
        db.query(Channel)
        .filter(
            Channel.id == channel_id,
            Channel.owner_id == current_user.id,
            Channel.is_active.is_(True),
        )
        .first()
    )

    if not channel:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Canal introuvable.",
        )

    username = channel.username

    if not username:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Ce canal ne possède pas de username Telegram.",
        )

    try:
        verification = telegram_service.verify_channel(
            username
        )
    except TelegramServiceError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise fastapi.HTTPException(
            status_code=502,
            detail="Impossible de contacter Telegram.",
        ) from exc

    if not verification:
        channel.telegram_verified = False
        channel.verification_note = (
            "Canal Telegram introuvable."
        )
        db.commit()

        raise fastapi.HTTPException(
            status_code=400,
            detail="Canal Telegram introuvable.",
        )

    telegram_chat_id = verification.get(
        "chat_id"
    )

    if telegram_chat_id is None:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Identifiant Telegram manquant.",
        )

    # --------------------------------------------------------
    # Vérification vendeur
    # --------------------------------------------------------

    try:
        seller_is_admin = telegram_service.verify_user_admin(
            telegram_chat_id,
            current_user.telegram_id,
        )
    except Exception:
        seller_is_admin = False

    # --------------------------------------------------------
    # Vérification bot
    # --------------------------------------------------------

    try:
        bot_is_admin = telegram_service.verify_bot_admin(
            telegram_chat_id
        )
    except Exception:
        bot_is_admin = False

    # --------------------------------------------------------
    # Mise à jour des informations
    # --------------------------------------------------------

    channel.telegram_chat_id = int(
        telegram_chat_id
    )

    if verification.get("title"):
        channel.title = verification.get(
            "title"
        )

    if verification.get("username"):
        channel.username = clean_username(
            verification.get("username")
        )

    if verification.get("description") is not None:
        channel.description = verification.get(
            "description"
        )

    if verification.get("photo_url") is not None:
        channel.photo_url = verification.get(
            "photo_url"
        )

    if verification.get("subscribers_count") is not None:
        channel.subscribers_count = int(
            verification.get(
                "subscribers_count",
                0,
            )
        )

    channel.seller_is_admin = bool(
        seller_is_admin
    )

    channel.bot_is_admin = bool(
        bot_is_admin
    )

    channel.telegram_verified = (
        bool(seller_is_admin)
        and bool(bot_is_admin)
    )

    channel.verified_at = (
        datetime.utcnow()
        if channel.telegram_verified
        else None
    )

    if channel.telegram_verified:
        channel.verification_note = (
            "Canal vérifié avec succès."
        )
    elif not bot_is_admin:
        channel.verification_note = (
            "Le bot NexMarket n'est pas administrateur "
            "du canal."
        )
    elif not seller_is_admin:
        channel.verification_note = (
            "Le vendeur n'est plus administrateur "
            "du canal."
        )

    db.commit()
    db.refresh(channel)

    return {
        "status": "success",
        "verified": channel.telegram_verified,
        "channel": channel_to_dict(channel),
    }


# ============================================================
# MODIFIER UN CANAL
# ============================================================


@router.patch("/{channel_id}")
def update_channel(
    channel_id: int,
    payload: ChannelUpdateRequest,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(get_current_user),
):
    channel = (
        db.query(Channel)
        .filter(
            Channel.id == channel_id,
            Channel.owner_id == current_user.id,
            Channel.is_active.is_(True),
        )
        .first()
    )

    if not channel:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Canal introuvable.",
        )

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    if payload.username is not None:
        username = clean_username(
            payload.username
        )

        if not username:
            raise fastapi.HTTPException(
                status_code=400,
                detail="Username Telegram invalide.",
            )

        if username != channel.username:
            duplicate = (
                db.query(Channel)
                .filter(
                    Channel.username == username,
                    Channel.id != channel.id,
                    Channel.is_active.is_(True),
                )
                .first()
            )

            if duplicate:
                raise fastapi.HTTPException(
                    status_code=409,
                    detail=(
                        "Ce canal est déjà enregistré "
                        "sur NexMarket."
                    ),
                )

            channel.username = username

            # Le changement de canal doit entraîner
            # une nouvelle vérification.
            channel.telegram_verified = False
            channel.bot_is_admin = False
            channel.seller_is_admin = False
            channel.verification_note = (
                "Le canal doit être revérifié."
            )
            channel.verified_at = None

    # --------------------------------------------------------
    # Autres informations
    # --------------------------------------------------------

    if payload.category is not None:
        channel.category = payload.category

    if payload.country is not None:
        channel.country = payload.country

    if payload.language is not None:
        channel.language = payload.language

    if payload.description is not None:
        channel.description = payload.description

    db.commit()
    db.refresh(channel)

    return {
        "status": "success",
        "message": "Canal mis à jour.",
        "channel": channel_to_dict(channel),
    }


# ============================================================
# DÉSACTIVER UN CANAL
# ============================================================


@router.delete("/{channel_id}")
def delete_channel(
    channel_id: int,
    db: Session = fastapi.Depends(get_db),
    current_user: User = fastapi.Depends(get_current_user),
):
    channel = (
        db.query(Channel)
        .filter(
            Channel.id == channel_id,
            Channel.owner_id == current_user.id,
            Channel.is_active.is_(True),
        )
        .first()
    )

    if not channel:
        raise fastapi.HTTPException(
            status_code=404,
            detail="Canal introuvable.",
        )

    channel.is_active = False

    db.commit()

    return {
        "status": "success",
        "message": "Canal retiré de NexMarket.",
    }