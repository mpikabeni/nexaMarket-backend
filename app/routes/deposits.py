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
from app.services.countries import COUNTRIES, is_supported, local_phone
from app.services import money_notifications
from app.config import settings
from app.services.deposit_sync import split_deposit, sync_deposit, total_to_pay
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
    # JessiKaPay EXIGE ce champ (HTTP 422 sinon).
    country: str = Field(..., min_length=2, max_length=2)


@router.post("")
async def create_deposit(
    payload: DepositIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.amount != payload.amount.to_integral_value():
        raise HTTPException(400, "Le montant doit être un nombre entier (XAF).")

    amount = int(payload.amount)
    commission, net = split_deposit(amount)

    if net < 1:
        raise HTTPException(400, "Montant trop faible pour un dépôt.")

    country = payload.country.strip().upper()

    if not is_supported(country):
        raise HTTPException(400, "Pays non pris en charge pour le dépôt.")

    phone = local_phone(country, payload.phone)

    if not 6 <= len(phone) <= 15:
        raise HTTPException(
            400,
            "Numéro invalide : entre ton numéro Mobile Money (sans l'indicatif).",
        )
    reference = "DEP-" + uuid4().hex[:20].upper()

    try:
        provider = await jessikapay_service.create_deposit(
            {
                "telegram_id": str(user.telegram_id),
                "name": user.first_name or user.username or "NexMarket",
                "country": country,
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
        country=country,
        jessikapay_request_id=str(request_id),
        jessikapay_code=provider.get("code"),
        payment_link=provider.get("payment_link"),
        commission_amount=commission,
        net_amount_credited=net,
        status=provider.get("status", "pending"),
        expires_at=None,
    )

    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    # L'utilisateur a confirmé : le bot l'informe qu'on attend JessiKaPay.
    await money_notifications.deposit_requested(db, dep)

    return {
        "id": dep.id,
        "reference": dep.reference,
        "amount": float(dep.amount),
        "commission_amount": float(commission),
        "net_amount": float(net),
        "total_to_pay": float(total_to_pay(dep.amount)),
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
            "net_amount": float(
                d.net_amount_credited
                if d.net_amount_credited is not None
                else split_deposit(d.amount)[1]
            ),
            "status": d.status,
            "created_at": d.created_at.isoformat(),
        }
        for d in rows
    ]


@router.post("/{deposit_id}/check")
async def check_deposit(
    deposit_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Vérifie auprès de JessiKaPay si le dépôt est payé (il n'y a plus
    de webhook) et crédite le wallet le cas échéant.
    """

    owned = (
        await db.execute(
            select(Deposit.id).where(
                Deposit.id == deposit_id,
                Deposit.user_id == user.id,
            )
        )
    ).first()

    if owned is None:
        raise HTTPException(404, "Dépôt introuvable.")

    status = await sync_deposit(db, deposit_id)

    return {"id": deposit_id, "status": status, "paid": status == "paid"}


@router.get("/fees")
async def deposit_fees():
    """Frais appliqués par JessiKaPay aux dépôts (affichés avant de payer)."""

    return {
        "commission_rate": settings.JESSIKAPAY_DEPOSIT_COMMISSION_RATE,
        "user_fee_rate": settings.JESSIKAPAY_USER_FEE_RATE,
    }


@router.get("/countries")
async def deposit_countries():
    """Pays disponibles pour un dépôt (nom, code ISO, indicatif)."""

    return {
        "countries": [
            {"code": code, "name": name, "dial": f"+{dial}"}
            for code, name, dial in COUNTRIES
        ]
    }
