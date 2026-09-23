# backend/app/deps.py

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_telegram_user_from_init_data
from app.db import get_db
from app.models.user import User


# =========================================================
# TELEGRAM INIT DATA
# =========================================================

def get_current_user(
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
    db: Session = Depends(get_db),
) -> User:
    """
    Récupère l'utilisateur actuellement connecté
    à partir des données authentifiées par Telegram.
    """

    if not x_telegram_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification Telegram requise.",
        )

    telegram_user = get_telegram_user_from_init_data(
        x_telegram_init_data
    )

    telegram_id = telegram_user.get("id")

    if not telegram_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant Telegram manquant.",
        )

    user = (
        db.query(User)
        .filter(User.telegram_id == int(telegram_id))
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur NexMarket introuvable.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte NexMarket est désactivé.",
        )

    return user


# =========================================================
# ADMIN USER
# =========================================================

def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Vérifie que l'utilisateur connecté est administrateur.
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès administrateur requis.",
        )

    return current_user
