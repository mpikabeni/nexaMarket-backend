from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.deposit import Deposit
from app.models.user import User
from app.services.jessikapay import JessiKaPayError, jessikapay_service

router = APIRouter(prefix="/deposits", tags=["Deposits"])

MAX_DEPOSIT_XAF = 5_000_000


class DepositIn(BaseModel):
    # Avant : `payload: dict` + int(float(...)) => 500 sur une valeur
    # invalide, aucun plafond, aucune validation du téléphone.
    amount: Decimal = Field(..., gt=0, le=MAX_DEPOSIT_XAF)
    # Numéro au format international (ex. +242060000000) : le pays est
    # déduit du numéro par JessiKaPay, il n'est plus demandé à l'utilisateur.
    phone: str = Field(..., min_length=6, max_length=40)


@router.post("")
async def create_deposit(
    payload: DepositIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.amount != payload.amount.to_integral_value():
        raise HTTPException(400, "Le montant doit être un nombre entier (XAF).")

    amount = int(payload.amount)
    phone = payload.phone.strip()
    reference = "DEP-" + uuid4().hex[:20].upper()

    try:
        provider = await jessikapay_service.create_deposit(
            {
                "telegram_id": str(user.telegram_id),
                "name": user.first_name or user.username or "NexMarket",
                "phone": phone,
                "amount": amount,
                "reference": reference,
            }
        )
    except JessiKaPayError as exc:
        raise HTTPException(502, str(exc)) from exc

    request_id = provider.get("request_id")

    if not request_id:
        raise HTTPException(502, "JessiKaPay n'a pas retourné de request_id.")

    dep = Deposit(
        user_id=user.id,
        reference=reference,
        amount=amount,
        currency="XAF",
        phone=phone,
        jessikapay_request_id=str(request_id),
        jessikapay_code=provider.get("code"),
        payment_link=provider.get("payment_link"),
        status=provider.get("status", "pending"),
        expires_at=None,
    )

    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    return {
        "id": dep.id,
        "reference": dep.reference,
        "amount": float(dep.amount),
        "status": dep.status,
        "payment_link": dep.payment_link,
        "code": dep.jessikapay_code,
    }


@router.get("/mine")
async def my_deposits(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(Deposit)
            .where(Deposit.user_id == user.id)
            .order_by(Deposit.created_at.desc())
            .limit(200)
        )
    ).scalars().all()

    return [
        {
            "id": d.id,
            "reference": d.reference,
            "amount": float(d.amount),
            "status": d.status,
            "created_at": d.created_at.isoformat(),
        }
        for d in rows
    ]
