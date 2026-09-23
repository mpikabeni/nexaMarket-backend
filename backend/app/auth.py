# backend/app/auth.py

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, status

from app.config import settings


# =========================================================
# TELEGRAM INIT DATA
# =========================================================

def validate_telegram_init_data(
    init_data: str,
    max_age: int = 86400,
) -> dict:
    """
    Vérifie cryptographiquement le initData fourni par Telegram
    lors de l'ouverture de la Mini App.

    Telegram utilise :

        secret_key = HMAC_SHA256("WebAppData", bot_token)

    puis :

        hash = HMAC_SHA256(secret_key, data_check_string)

    Retourne les données Telegram vérifiées.
    """

    if not init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram initData manquant.",
        )

    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Telegram bot token non configuré.",
        )

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram initData invalide.",
        ) from exc

    received_hash = parsed.pop("hash", None)

    if not received_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hash Telegram manquant.",
        )

    # =====================================================
    # CHECK DATA
    # =====================================================

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(parsed.items())
    )

    # =====================================================
    # SECRET KEY
    # =====================================================

    secret_key = hmac.new(
        b"WebAppData",
        settings.TELEGRAM_BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    # =====================================================
    # EXPECTED HASH
    # =====================================================

    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Comparaison résistante au timing attack
    if not hmac.compare_digest(
        expected_hash,
        received_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification Telegram invalide.",
        )

    # =====================================================
    # AUTH_DATE
    # =====================================================

    auth_date_raw = parsed.get("auth_date")

    if not auth_date_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth_date Telegram manquant.",
        )

    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth_date Telegram invalide.",
        ) from exc

    current_time = int(time.time())

    # Protection contre un initData trop ancien
    if current_time - auth_date > max_age:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram initData expiré.",
        )

    # Protection basique contre une date future anormale
    if auth_date - current_time > 60:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Date Telegram invalide.",
        )

    # =====================================================
    # CONVERT JSON FIELDS
    # =====================================================

    if "user" in parsed:
        try:
            parsed["user"] = json.loads(parsed["user"])
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Données utilisateur Telegram invalides.",
            )

    if "receiver" in parsed:
        try:
            parsed["receiver"] = json.loads(parsed["receiver"])
        except json.JSONDecodeError:
            pass

    return parsed


# =========================================================
# TELEGRAM USER
# =========================================================

def get_telegram_user_from_init_data(
    init_data: str,
) -> dict:
    """
    Vérifie initData puis récupère l'utilisateur Telegram.
    """

    data = validate_telegram_init_data(init_data)

    telegram_user = data.get("user")

    if not telegram_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur Telegram introuvable.",
        )

    if not isinstance(telegram_user, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur Telegram invalide.",
        )

    telegram_id = telegram_user.get("id")

    if not telegram_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant Telegram manquant.",
        )

    return telegram_user


# =========================================================
# TELEGRAM ID
# =========================================================

def get_telegram_id_from_init_data(
    init_data: str,
) -> int:
    """
    Retourne uniquement le Telegram ID après vérification.
    """

    user = get_telegram_user_from_init_data(init_data)

    try:
        return int(user["id"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram ID invalide.",
        ) from exc