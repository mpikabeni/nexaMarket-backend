"""Client JessiKaPay (API externe signée HMAC-SHA256).

Doc : https://jkpay.vercel.app/docs
- Dépôt externe : l'acheteur paie en Mobile Money via un lien Telegram.
  Il paie +3 %, NexMarket est crédité de -6 % du montant demandé.
- Payout : envoi GRATUIT vers le numéro JP (compte JessiKaPay) d'un utilisateur.
  Il est immédiat : une réponse success=true = argent déjà arrivé.

JessiKaPayError hérite de MoneyFusionError : tout le code existant qui attrape
MoneyFusionError (handlers, boucles de contrôle) continue de fonctionner.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx

from app.config import settings
from app.services.moneyfusion import MoneyFusionError

logger = logging.getLogger("nexmarket.jessikapay")


class JessiKaPayError(MoneyFusionError):
    pass


def normalize_jp(value: str) -> str:
    """Accepte « jp-123456 », « 123456 »… et renvoie « JP-123456 »."""
    raw = (value or "").strip().upper().replace(" ", "")
    if not raw:
        return ""
    return raw if raw.startswith("JP-") else f"JP-{raw.removeprefix('JP')}"


class JessiKaPayService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return (settings.JESSIKAPAY_BASE_URL or "").rstrip("/")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=6.0, read=25.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            )
        return self._client

    def _headers(self, body: str) -> dict[str, str]:
        key = (settings.JESSIKAPAY_API_KEY or "").strip()
        secret = (settings.JESSIKAPAY_API_SECRET or "").strip()
        if not (key and secret and self.base_url):
            raise JessiKaPayError(
                "Le paiement n'est pas configuré (JESSIKAPAY_API_KEY / API_SECRET)."
            )
        timestamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
        ).hexdigest()
        return {
            "X-API-Key": key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, payload: dict | None = None):
        # Corps signé = corps envoyé, octet pour octet.
        body = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            if payload is not None
            else ""
        )
        headers = self._headers(body)

        try:
            response = await self._get_client().request(
                method,
                f"{self.base_url}{path}",
                content=body.encode() if body else None,
                headers=headers,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Rien n'est parti : on peut réessayer sans risque.
            raise JessiKaPayError(
                "Le service de paiement est injoignable. Réessaie dans un instant.",
                ambiguous=False,
            ) from exc
        except httpx.RequestError as exc:
            raise JessiKaPayError(
                f"Réponse du service de paiement inconnue ({type(exc).__name__}).",
                ambiguous=True,
            ) from exc

        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                data = response.json()
                if isinstance(data, dict) and data.get("detail"):
                    detail = str(data["detail"])[:300]
            except ValueError:
                pass
            raise JessiKaPayError(
                f"Paiement refusé ({response.status_code}) : {detail}",
                ambiguous=response.status_code >= 500,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise JessiKaPayError(
                "Réponse invalide du service de paiement.", ambiguous=True
            ) from exc

    # ---------------- dépôt externe (achat direct) ----------------

    async def create_deposit(
        self, *, telegram_id: int, name: str, country: str, phone: str,
        amount: int, reference: str, expires_in_minutes: int = 30,
    ) -> dict:
        data = await self._request(
            "POST",
            "/external/v1/deposit-request",
            {
                "telegram_id": int(telegram_id),
                "name": name[:60] or "NexMarket",
                "country": country.upper(),
                "phone": phone,
                "amount": int(amount),
                "reference": reference,
                "expires_in_minutes": expires_in_minutes,
            },
        )
        if not isinstance(data, dict) or not data.get("request_id") or not data.get("payment_link"):
            raise JessiKaPayError("Le service de paiement n'a pas renvoyé de lien.", ambiguous=True)
        return {
            "token": str(data["request_id"]),
            "url": str(data["payment_link"]),
            "code": data.get("code"),
        }

    async def get_payment_status(self, request_id: str) -> dict:
        """Statuts : pending, reviewing, awaiting_payment, paid, failed, expired."""
        return await self._request("GET", f"/external/v1/deposit-request/{request_id}/status")

    # ---------------- payout vers un numéro JP (gratuit, immédiat) ----------------

    async def lookup(self, jp_number: str) -> dict:
        jp = normalize_jp(jp_number)
        if not jp:
            return {"found": False}
        data = await self._request("GET", f"/external/v1/payout/lookup/{jp}")
        return data if isinstance(data, dict) else {"found": False}

    async def payout(self, *, jp_number: str, amount: int, reference: str,
                     description: str = "") -> dict:
        data = await self._request(
            "POST",
            "/external/v1/payout",
            {
                "jp_number": normalize_jp(jp_number),
                "amount": int(amount),
                "reference": reference,
                "description": description[:120],
            },
        )
        if not (isinstance(data, dict) and data.get("success") and data.get("transaction_id")):
            # Réponse sans confirmation : peut-être payé -> un humain vérifie.
            raise JessiKaPayError(
                "Versement non confirmé par le service de paiement.", ambiguous=True
            )
        return {"token": str(data["transaction_id"])}

    async def get_payout_status(self, token: str) -> dict:
        """Un payout JessiKaPay est immédiat : un jeton existe seulement si le
        versement a réussi (success=true), donc il est déjà terminé."""
        return {"status": "completed", "token": token}


jessikapay_service = JessiKaPayService()
