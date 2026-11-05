"""Photos de preuve d'une annonce : validation et décodage."""

from __future__ import annotations

import base64
import binascii

MAX_PROOFS = 4
MAX_PROOF_BYTES = 1_200_000  # après compression côté Mini App (~200-400 Ko)


def _detect_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_proofs(images: list[str]) -> list[tuple[str, bytes]]:
    """
    Décode les images envoyées par la Mini App (data URL ou base64).
    Le type est lu dans les OCTETS de l'image (jamais déclaré par le client).
    Lève ValueError avec un message lisible.
    """

    if not images:
        raise ValueError(
            "Ajoute au moins une photo de preuve (capture des statistiques "
            "de ton canal) : elle est envoyée à l'administrateur."
        )

    if len(images) > MAX_PROOFS:
        raise ValueError(f"Maximum {MAX_PROOFS} photos de preuve.")

    result: list[tuple[str, bytes]] = []

    for index, raw in enumerate(images, start=1):
        payload = raw.split(",", 1)[1] if raw.startswith("data:") and "," in raw else raw

        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"La photo {index} n'est pas une image valide.")

        if len(data) > MAX_PROOF_BYTES:
            raise ValueError(
                f"La photo {index} est trop lourde (max "
                f"{MAX_PROOF_BYTES // 1000} Ko)."
            )

        content_type = _detect_type(data)

        if content_type is None:
            raise ValueError(
                f"La photo {index} doit être au format JPEG, PNG ou WebP."
            )

        result.append((content_type, data))

    return result
