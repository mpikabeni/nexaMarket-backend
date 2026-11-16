"""Notifications de JessiKaPay (webhooks).

Un webhook ne crédite JAMAIS rien tout seul :
- credit.completed  : un retrait « à vérifier » est terminé (JessiKaPay confirme
  avoir payé, signature vérifiée) ;
- deposit.completed : on lance aussitôt la vérification du dépôt auprès de
  JessiKaPay (le crédit n'a lieu qu'après cette vérification).
Les endpoints de statut et la boucle de contrôle restent le filet de sécurité.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import settings
from app.deps import DBSession
from app.models.deposit import Deposit
from app.models.withdrawal import Withdrawal
from app.services import money_notifications
from app.services.deposit_sync import sync_deposit
from app.services.payout_settlement import complete_withdrawal
from app.services.webhook_security import verify_signature

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger("nexmarket.webhooks")


@router.post("/jessikapay")
async def jessikapay_webhook(request: Request, db: DBSession):
    raw = await request.body()

    if not verify_signature(
        settings.JESSIKAPAY_API_SECRET,
        request.headers.get("X-JessiKaPay-Timestamp", ""),
        request.headers.get("X-JessiKaPay-Signature", ""),
        raw,
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signature invalide.")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Corps invalide.")

    event = payload.get("event")
    reference = payload.get("reference")

    if event == "credit.completed" and reference:
        withdrawal = (
            await db.execute(
                select(Withdrawal).where(Withdrawal.reference == reference).with_for_update()
            )
        ).scalar_one_or_none()
        if withdrawal and withdrawal.status in ("processing", "pending"):
            if payload.get("transaction_id") and not withdrawal.jessikapay_transaction_id:
                withdrawal.jessikapay_transaction_id = str(payload["transaction_id"])
            await complete_withdrawal(db, withdrawal)
            await money_notifications.withdrawal_completed(db, withdrawal)
            logger.info("Retrait %s terminé par webhook", reference)

    elif event == "deposit.completed":
        request_id = payload.get("request_id")
        query = select(Deposit)
        if request_id:
            query = query.where(Deposit.jessikapay_request_id == str(request_id))
        elif reference:
            query = query.where(Deposit.reference == reference)
        else:
            return {"ok": True}
        deposit = (await db.execute(query)).scalar_one_or_none()
        if deposit:
            await sync_deposit(db, deposit.id)  # vérifie auprès de JessiKaPay avant de créditer

    return {"ok": True}
