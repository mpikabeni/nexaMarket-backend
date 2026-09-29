import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import jwt
from fastapi import HTTPException, status

from app.config import settings


# ============================================================
# TELEGRAM MINI APP AUTH
# ============================================================

def validate_telegram_init_data(
    init_data: str,
) -> dict:
    """
    Vérifie les données initData envoyées par Telegram
    lors de l'ouverture de la Mini App.

    Telegram signe les données avec le bot token.

    Retourne les données utilisateur décodées si la
    signature est valide.
    """

    if not init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Données Telegram manquantes.",
        )

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Données Telegram invalides.",
        )

    received_hash = parsed.pop("hash", None)

    if not received_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature Telegram manquante.",
        )

    auth_date_raw = parsed.get("auth_date")

    if not auth_date_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Date d'authentification Telegram manquante.",
        )

    try:
        auth_date = int(auth_date_raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Date Telegram invalide.",
        )

    current_timestamp = int(time.time())

    if current_timestamp - auth_date > settings.TELEGRAM_AUTH_MAX_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session Telegram expirée.",
        )

    if auth_date > current_timestamp + 60:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Date Telegram invalide.",
        )

    # --------------------------------------------------------
    # Création du data-check-string Telegram
    # --------------------------------------------------------

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(parsed.items())
    )

    # --------------------------------------------------------
    # Secret key Telegram
    # --------------------------------------------------------

    secret_key = hmac.new(
        b"WebAppData",
        settings.TELEGRAM_BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_hash,
        received_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature Telegram invalide.",
        )

    # --------------------------------------------------------
    # Récupération des données utilisateur
    # --------------------------------------------------------

    user_raw = parsed.get("user")

    if not user_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur Telegram manquant.",
        )

    try:
        telegram_user = json.loads(user_raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Données utilisateur Telegram invalides.",
        )

    telegram_id = telegram_user.get("id")

    if not telegram_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant Telegram manquant.",
        )

    return {
        "telegram_id": int(telegram_id),
        "username": telegram_user.get("username"),
        "first_name": telegram_user.get("first_name"),
        "last_name": telegram_user.get("last_name"),
        "photo_url": telegram_user.get("photo_url"),
        "auth_date": auth_date,
        "query_id": parsed.get("query_id"),
    }


# ============================================================
# JWT
# ============================================================

def create_access_token(
    user_id: int,
) -> str:
    """
    Crée le JWT utilisé par le frontend pour les requêtes API.
    """

    now = datetime.now(timezone.utc)

    expires_at = now + timedelta(
        minutes=settings.JWT_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
