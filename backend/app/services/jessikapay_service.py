from __future__ import annotations
import hashlib, hmac, time
import httpx
from app.config import settings

class JessiKaPayError(Exception): pass

class JessiKaPayService:
    def __init__(self):
        self.base_url = settings.JESSIKAPAY_API_URL.rstrip("/")
    def _headers(self, body: str = "") -> dict[str,str]:
        if not settings.JESSIKAPAY_API_KEY or not settings.JESSIKAPAY_API_SECRET:
            raise JessiKaPayError("JessiKaPay credentials are not configured")
        ts = str(int(time.time()))
        signature = hmac.new(settings.JESSIKAPAY_API_SECRET.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        return {"X-API-Key": settings.JESSIKAPAY_API_KEY, "X-Timestamp": ts, "X-Signature": signature, "Content-Type": "application/json"}
    async def _request(self, method, path, payload=None):
        import json
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) if payload is not None else ""
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request(method, self.base_url + path, content=body, headers=self._headers(body))
        if r.status_code >= 400: raise JessiKaPayError(f"JessiKaPay HTTP {r.status_code}: {r.text[:500]}")
        return r.json()
    async def create_deposit(self, payload): return await self._request("POST", "/external/v1/deposit-request", payload)
    async def get_deposit(self, request_id): return await self._request("GET", f"/external/v1/deposit-request/{request_id}/status")
    async def create_payment(self, payload): return await self._request("POST", "/external/v1/payment-request", payload)
    async def get_payment(self, request_id): return await self._request("GET", f"/external/v1/payment-request/{request_id}/status")
    async def payout(self, payload): return await self._request("POST", "/external/v1/payout", payload)
    async def lookup_jp(self, jp_number): return await self._request("GET", f"/external/v1/payout/lookup/{jp_number}")

jessikapay_service = JessiKaPayService()
