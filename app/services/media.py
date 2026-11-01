"""URLs publiques des médias (photos de canaux)."""

from __future__ import annotations

import os

from app.config import settings


def public_base_url() -> str:
    """URL publique de l'API : PUBLIC_URL, sinon celle fournie par Render."""

    return (
        settings.PUBLIC_URL
        or os.environ.get("RENDER_EXTERNAL_URL", "")
    ).rstrip("/")


def channel_photo_url(channel) -> str | None:
    """
    Les photos sont stockées sous la forme « tg:<file_id Telegram> ».
    On ne les expose JAMAIS via l'URL Telegram (elle contient le token du
    bot) : elles passent par GET /api/channels/{id}/photo.
    """

    photo = getattr(channel, "photo_url", None)

    if not photo:
        return None

    if photo.startswith("tg:"):
        base = public_base_url()
        path = f"/api/channels/{channel.id}/photo"
        return f"{base}{path}" if base else path

    return photo
