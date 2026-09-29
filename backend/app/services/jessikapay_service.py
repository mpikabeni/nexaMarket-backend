from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.config import settings


class JessiKaPayError(Exception):
    """Erreur provenant du service JessiKaPay."""


class JessiKaPayService:
    """
    Client API JessiKaPay pour NexMarket.

    Les secrets restent exclusivement côté backend.
    """

    def __init__(self) -> None:
        self.base_url = settings.JESSIKAPAY_API_URL.rstrip("/")
        self.api_key = settings.JESSIKAPAY_API_KEY
        self.api_secret = settings.JESSIKAPAY_API_SECRET

    # ========================================================
    # CONFIGURATION
    # ========================================================

    def _check_credentials(self) -> None:
        if not self.api_key or not self.api_secret:
            raise JessiKaPayError(
                "Les identifiants JessiKaPay ne sont pas configurés."
            )

    # ========================================================
    # SIGNATURE HMAC-SHA256
    # ========================================================

    def _sign(
        self,
        timestamp: int,
        body: str,
    ) -> str:
        """
        Signature JessiKaPay :

            HMAC-SHA256(
                f"{timestamp}.{body}",
                api_secret
            )
        """

        message = f"{timestamp}.{body}"

        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(
        self,
        timestamp: int,
        body: str,
    ) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "X-Timestamp": str(timestamp),
            "X-Signature": self._sign(
                timestamp,
                body,
            ),
            "Content-Type": "application/json",
        }

    # ========================================================
    # HTTP
    # ========================================================

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._check_credentials()

        body = ""

        if payload is not None:
            body = json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=False,
            )

        timestamp = int(time.time())

        headers = self._headers(
            timestamp,
            body,
        )

        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(
            timeout=30.0,
        ) as client:

            try:
                if method.upper() == "GET":
                    response = await client.get(
                        url,
                        headers=headers,
                    )
                elif method.upper() == "POST":
                    response = await client.post(
                        url,
                        headers=headers,
                        content=body,
                    )
                else:
                    raise JessiKaPayError(
                        f"Méthode HTTP non supportée : {method}"
                    )

            except httpx.RequestError as exc:
                raise JessiKaPayError(
                    f"Erreur de connexion JessiKaPay : {exc}"
                ) from exc

        try:
            data = response.json()
        except ValueError:
            data = {
                "raw_response": response.text,
            }

        if response.status_code >= 400:
            raise JessiKaPayError(
                self._extract_error(
                    data,
                    response.status_code,
                )
            )

        if not isinstance(data, dict):
            raise JessiKaPayError(
                "Réponse JessiKaPay invalide."
            )

        return data

    @staticmethod
    def _extract_error(
        data: Any,
        status_code: int,
    ) -> str:
        if isinstance(data, dict):
            for key in (
                "detail",
                "message",
                "error",
            ):
                value = data.get(key)

                if value:
                    return (
                        f"JessiKaPay ({status_code}) : "
                        f"{value}"
                    )

        return (
            f"JessiKaPay a retourné HTTP "
            f"{status_code}."
        )

    # ========================================================
    # EXTERNAL DEPOSIT
    # ========================================================

    async def create_deposit_request(
        self,
        *,
        telegram_id: int,
        name: str,
        country: str,
        phone: str,
        amount: int,
        reference: str,
        expires_in_minutes: int = 30,
    ) -> dict[str, Any]:
        """
        Crée une demande de dépôt externe.

        Endpoint :
            POST /external/v1/deposit-request
        """

        payload = {
            "telegram_id": telegram_id,
            "name": name,
            "country": country,
            "phone": phone,
            "amount": amount,
            "reference": reference,
            "expires_in_minutes": expires_in_minutes,
        }

        return await self._request(
            "POST",
            "/external/v1/deposit-request",
            payload,
        )

    # ========================================================
    # DEPOSIT STATUS
    # ========================================================

    async def get_deposit_status(
        self,
        request_id: str,
    ) -> dict[str, Any]:
        """
        Récupère le statut d'une demande de dépôt.

        Endpoint documenté :
            GET /external/v1/deposit-request/{request_id}/status
        """

        return await self._request(
            "GET",
            f"/external/v1/deposit-request/{request_id}/status",
        )

    # ========================================================
    # PAYMENT REQUEST
    # ========================================================

    async def create_payment_request(
        self,
        *,
        jp_number: str,
        amount: int,
        reference: str,
        description: str,
        expires_in_minutes: int = 30,
    ) -> dict[str, Any]:
        """
        Crée une demande de paiement vers un compte
        JessiKaPay existant.

        Endpoint :
            POST /external/v1/payment-request
        """

        payload = {
            "jp_number": jp_number,
            "amount": amount,
            "reference": reference,
            "description": description,
            "expires_in_minutes": expires_in_minutes,
        }

        return await self._request(
            "POST",
            "/external/v1/payment-request",
            payload,
        )

    # ========================================================
    # PAYMENT STATUS
    # ========================================================

    async def get_payment_status(
        self,
        request_id: str,
    ) -> dict[str, Any]:
        """
        Vérifie le statut d'une demande de paiement.

        Endpoint :
            GET /external/v1/payment-request/{request_id}/status
        """

        return await self._request(
            "GET",
            f"/external/v1/payment-request/{request_id}/status",
        )

    # ========================================================
    # PAYOUT
    # ========================================================

    async def create_payout(
        self,
        *,
        jp_number: str,
        amount: int,
        reference: str,
        description: str,
    ) -> dict[str, Any]:
        """
        Effectue un payout vers le JP du vendeur.

        Endpoint :
            POST /external/v1/payout

        IMPORTANT :
        Après une requête envoyée, NexMarket ne doit pas
        effectuer automatiquement une seconde requête en
        cas de timeout.

        Le statut/webhook doit d'abord être vérifié.
        """

        payload = {
            "jp_number": jp_number,
            "amount": amount,
            "reference": reference,
            "description": description,
        }

        return await self._request(
            "POST",
            "/external/v1/payout",
            payload,
        )

    # ========================================================
    # JP LOOKUP
    # ========================================================

    async def lookup_jp(
        self,
        jp_number: str,
    ) -> dict[str, Any]:
        """
        Recherche un compte JessiKaPay.

        Endpoint :
            GET /external/v1/payout/lookup/{jp_number}
        """

        normalized = jp_number.strip()

        return await self._request(
            "GET",
            f"/external/v1/payout/lookup/{normalized}",
        )
