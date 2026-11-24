"""Notifications de MoneyFusion (webhooks).

Les webhooks MoneyFusion NE SONT PAS SIGNÉS (aucune signature dans leur doc) :
n'importe qui pourrait en envoyer un faux. Deux protections :

1. l'URL contient un segment secret (MONEYFUSION_WEBHOOK_SECRET) : sans lui, 404 ;
2. un webhook ne crédite et ne débloque JAMAIS rien tout seul. Il sert
   uniquement de déclencheur : on relit le statut auprès de l'API MoneyFusion
   (avec notre clé) et seul ce résultat fait foi.

Événements : payin.session.pending / completed / cancelled (dépôts) et
payout.session.completed / cancelled (retraits). La boucle de contrôle de
main.py reste le filet de sécurité si un webhook est perdu ou en double.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import settings
from app.deps import DBSession
from app.models.deposit import Deposit
from app.models.platform import CommissionPayout
from app.models.withdrawal import Withdrawal
from app.services.deposit_sync import sync_deposit
from app.services.payout_sync import sync_commission_payout, sync_withdrawal

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger("nexmarket.webhooks")


def _secret_ok(provided: str) -> bool:
    expected = (settings.MONEYFUSION_WEBHOOK_SECRET or "").strip()

    if not expected:
        return False  # webhook désactivé

    return hmac.compare_digest(provided.encode(), expected.encode())


@router.post("/moneyfusion/{secret}")
async def moneyfusion_webhook(secret: str, request: Request, db: DBSession):
    if not _secret_ok(secret):
        # 404 (et non 401) : ne révèle pas que le point d'entrée existe.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    raw = await request.body()

    if len(raw) > 64_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Corps trop volumineux.")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Corps invalide.")

    if not isinstance(payload, dict):
        return {"ok": True}

    event = str(payload.get("event") or "")
    token = str(payload.get("tokenPay") or "").strip()

    if not token or len(token) > 255:
        return {"ok": True}

    if event.startswith("payin."):
        deposit = (
            await db.execute(select(Deposit).where(Deposit.jessikapay_request_id == token))
        ).scalar_one_or_none()

        if deposit:
            # Vérifie auprès de MoneyFusion avant de créditer.
            await sync_deposit(db, deposit.id)

    elif event.startswith("payout."):
        withdrawal = (
            await db.execute(select(Withdrawal).where(Withdrawal.jessikapay_transaction_id == token))
        ).scalar_one_or_none()

        if withdrawal:
            await sync_withdrawal(db, withdrawal.id)
        else:
            commission = (
                await db.execute(
                    select(CommissionPayout).where(CommissionPayout.jessikapay_transaction_id == token)
                )
            ).scalar_one_or_none()

            if commission:
                await sync_commission_payout(db, commission.id)

    else:
        logger.info("Webhook MoneyFusion ignoré (événement %r)", event[:60])

    return {"ok": True}


@router.post("/jessikapay")
async def jessikapay_webhook(request: Request, db: DBSession):
    """Webhook JessiKaPay : signature HMAC-SHA256 de « {timestamp}.{corps brut} ».

    Il ne fait que déclencher une vérification : le crédit n'a lieu qu'après
    relecture du statut auprès de l'API (la boucle de contrôle reste le filet)."""

    import hashlib
    import time

    secret = (settings.JESSIKAPAY_API_SECRET or "").strip()
    raw = await request.body()
    timestamp = request.headers.get("X-JessiKaPay-Timestamp", "")
    signature = request.headers.get("X-JessiKaPay-Signature", "")

    try:
        fresh = abs(time.time() - int(timestamp)) <= 300
    except ValueError:
        fresh = False

    expected = (
        hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
        if secret
        else ""
    )

    if not (secret and fresh and hmac.compare_digest(expected, signature)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    try:
        payload = json.loads(raw)
    except ValueError:
        return {"ok": True}

    if isinstance(payload, dict) and payload.get("event") == "deposit.completed":
        request_id = str(payload.get("request_id") or "").strip()
        deposit = (
            await db.execute(select(Deposit).where(Deposit.jessikapay_request_id == request_id))
        ).scalar_one_or_none()

        if deposit:
            await sync_deposit(db, deposit.id)

    return {"ok": True}
