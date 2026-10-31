from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from app.config import settings


class JessiKaPayError(Exception):
    """
    Erreur liée à l'API JessiKaPay.

    ambiguous=True signifie que l'issue est INCONNUE (timeout, erreur
    réseau, réponse 5xx) : le prestataire a peut-être quand même traité
    la demande. Dans ce cas il ne faut jamais rendre l'argent à
    l'utilisateur automatiquement (risque de double paiement) : il faut
    réconcilier avec le prestataire.
    """

    def __init__(self, message: str = "", *, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


class JessiKaPayService:
    def __init__(self):
        self.base_url = (
            settings.JESSIKAPAY_API_URL
            .rstrip("/")
        )

    def _headers(
        self,
        body: str = "",
    ) -> dict[str, str]:

        api_key = (
            settings.JESSIKAPAY_API_KEY
            or ""
        ).strip()

        api_secret = (
            settings.JESSIKAPAY_API_SECRET
            or ""
        ).strip()

        if not api_key or not api_secret:
            raise JessiKaPayError(
                "JessiKaPay credentials are not configured."
            )

        timestamp = str(int(time.time()))

        message = f"{timestamp}.{body}"

        signature = hmac.new(
            api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-API-Key": api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
    ):
        body = ""

        if payload is not None:
            body = json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=False,
            )

        headers = self._headers(body)

        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient(
                timeout=30.0
            ) as client:

                response = await client.request(
                    method=method,
                    url=url,
                    content=body,
                    headers=headers,
                )

        except httpx.RequestError as exc:
            raise JessiKaPayError(
                f"Impossible de contacter JessiKaPay: {exc}",
                ambiguous=True,
            ) from exc

        if response.status_code >= 400:
            raise JessiKaPayError(
                "JessiKaPay HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}",
                ambiguous=response.status_code >= 500,
            )

        try:
            return response.json()

        except ValueError as exc:
            raise JessiKaPayError(
                "JessiKaPay a retourné une réponse "
                "JSON invalide.",
                ambiguous=True,
            ) from exc

    # ========================================================
    # DEPOSIT
    # ========================================================

    async def create_deposit(
        self,
        payload: dict,
    ):
        return await self._request(
            "POST",
            "/external/v1/deposit-request",
            payload,
        )

    async def get_deposit(
        self,
        request_id: str,
    ):
        return await self._request(
            "GET",
            (
                "/external/v1/deposit-request/"
                f"{request_id}/status"
            ),
        )

    # ========================================================
    # PAYMENT REQUEST
    # ========================================================

    async def create_payment(
        self,
        payload: dict,
    ):
        return await self._request(
            "POST",
            "/external/v1/payment-request",
            payload,
        )

    async def get_payment(
        self,
        request_id: str,
    ):
        return await self._request(
            "GET",
            (
                "/external/v1/payment-request/"
                f"{request_id}/status"
            ),
        )

    # ========================================================
    # PAYOUT
    # ========================================================

    async def payout(
        self,
        payload: dict,
    ):
        return await self._request(
            "POST",
            "/external/v1/payout",
            payload,
        )

    # ========================================================
    # PAYOUT LOOKUP
    # ========================================================

    async def lookup_jp(
        self,
        jp_number: str,
    ):
        return await self._request(
            "GET",
            (
                "/external/v1/payout/lookup/"
                f"{jp_number}"
            ),
        )

    # ========================================================
    # MÉTHODES UTILISÉES PAR LES SERVICES MÉTIER
    # (les services appelaient des noms qui n'existaient pas)
    # ========================================================

    async def create_deposit_request(
        self,
        *,
        telegram_id: int | str,
        name: str,
        phone: str,
        amount: int,
        reference: str,
    ):
        return await self.create_deposit(
            {
                "telegram_id": str(telegram_id),
                "name": name,
                "phone": phone,
                "amount": amount,
                "reference": reference,
            }
        )

    async def get_deposit_status(self, request_id: str):
        return await self.get_deposit(request_id)

    async def create_payment_request(
        self,
        *,
        jp_number: str,
        amount: int,
        reference: str,
        description: str,
    ):
        # ATTENTION : les clés ci-dessous sont déduites du reste du
        # code. Vérifiez-les avec la documentation JessiKaPay
        # (endpoint /external/v1/payment-request).
        payload = {
            "jp_number": jp_number,
            "amount": amount,
            "reference": reference,
            "description": description,
        }

        if settings.JESSIKAPAY_WEBHOOK_URL:
            payload["webhook_url"] = settings.JESSIKAPAY_WEBHOOK_URL

        return await self.create_payment(payload)

    async def create_payout(
        self,
        *,
        jp_number: str,
        amount: int,
        reference: str,
        description: str,
    ):
        return await self.payout(
            {
                "jp_number": jp_number,
                "amount": amount,
                "reference": reference,
                "description": description,
            }
        )


jessikapay_service = JessiKaPayService()
