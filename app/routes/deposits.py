from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.deposit import Deposit
from app.models.listing import Listing
from app.models.user import User
from app.services.countries import local_phone
from app.services import money_notifications
from app.config import settings
from app.services.deposit_sync import split_deposit, sync_deposit, total_to_pay
from app.services.jessikapay import jessikapay_service
from app.services.moneyfusion import (
    CFA_CURRENCIES,
    MoneyFusionError,
    moneyfusion_service,
    public_catalog,
)

router = APIRouter(prefix="/deposits", tags=["Deposits"])

MAX_DEPOSIT_XAF = 5_000_000


class DepositIn(BaseModel):
    # Avant : `payload: dict` + int(float(...)) => 500 sur une valeur
    # invalide, aucun plafond, aucune validation du téléphone.
    amount: Decimal = Field(..., gt=0, le=MAX_DEPOSIT_XAF)
    # Numéro Mobile Money de l'utilisateur (avec ou sans indicatif « + » / « 00 »).
    phone: str = Field(..., min_length=6, max_length=40)
    country: str = Field(..., min_length=2, max_length=2)


async def _deposit_countries() -> list[dict]:
    """Pays de dépôt : ceux de MoneyFusion à devise CFA (XOF/XAF, parité 1:1 avec le wallet XAF)."""

    countries, _source = await moneyfusion_service.get_countries()

    return [c for c in public_catalog(countries) if c["currency"] in CFA_CURRENCIES]


def _webhook_url() -> str:
    base = (settings.PUBLIC_URL or "").strip().rstrip("/")
    secret = (settings.MONEYFUSION_WEBHOOK_SECRET or "").strip()

    return f"{base}/webhooks/moneyfusion/{secret}" if base and secret else ""


@router.post("")
async def create_deposit(
    payload: DepositIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    raise HTTPException(410, "Les dépôts ne sont plus proposés : paie directement un canal.")

    if payload.amount != payload.amount.to_integral_value():
        raise HTTPException(400, "Le montant doit être un nombre entier (XAF).")

    amount = int(payload.amount)
    commission, net = split_deposit(amount)

    if net < 1:
        raise HTTPException(400, "Montant trop faible pour un dépôt.")

    country = payload.country.strip().upper()

    if country not in {c["code"] for c in await _deposit_countries()}:
        raise HTTPException(400, "Pays non pris en charge pour le dépôt.")

    phone = local_phone(country, payload.phone)

    if not 6 <= len(phone) <= 15:
        raise HTTPException(
            400,
            "Numéro invalide : entre ton numéro Mobile Money (sans l'indicatif).",
        )
    reference = "DEP-" + uuid4().hex[:20].upper()

    try:
        provider = await moneyfusion_service.create_payment(
            amount=amount,
            phone=phone,
            name=user.first_name or user.username or "NexMarket",
            reference=reference,
            user_id=user.id,
            return_url=(settings.FRONTEND_URL or "").strip(),
            webhook_url=_webhook_url(),
        )
    except MoneyFusionError as exc:
        raise HTTPException(502, str(exc)) from exc

    dep = Deposit(
        user_id=user.id,
        reference=reference,
        amount=amount,
        currency="XAF",
        phone=phone,
        country=country,
        # Jeton MoneyFusion (colonne au nom historique) : sert à relire le statut.
        jessikapay_request_id=provider["token"],
        jessikapay_code=None,
        payment_link=provider["url"],
        commission_amount=commission,
        net_amount_credited=net,
        status="pending",
        expires_at=None,
    )

    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    # L'utilisateur a confirmé : le bot l'informe qu'on attend MoneyFusion.
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
        "code": None,
    }


class PurchaseIn(BaseModel):
    listing_id: int
    # Par défaut : pays et numéro du compte (saisis à l'inscription).
    country: str | None = Field(default=None, min_length=2, max_length=2)
    phone: str | None = Field(default=None, min_length=6, max_length=40)


@router.post("/purchase", status_code=201)
async def pay_for_listing(
    payload: PurchaseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Achat direct d'un canal : paiement MoneyFusion, sans dépôt préalable.

    Une fois le paiement confirmé, l'achat est créé AUTOMATIQUEMENT et l'argent est
    bloqué dans le wallet, comme d'habitude, jusqu'à la libération par l'admin.
    """

    listing = (
        await db.execute(select(Listing).where(Listing.id == payload.listing_id))
    ).scalar_one_or_none()

    if listing is None or not listing.is_public or listing.status != "published":
        raise HTTPException(400, "Cette annonce n'est plus disponible.")

    if listing.seller_id == user.id:
        raise HTTPException(400, "Vous ne pouvez pas acheter votre propre annonce.")

    if (listing.currency or "XAF").upper() != "XAF":
        raise HTTPException(400, "Cette annonce se paie en GRAM.")

    country = (payload.country or user.country or "").strip().upper()
    phone = local_phone(country, payload.phone or user.phone or "") if country else ""

    if not country:
        raise HTTPException(400, "Choisis ton pays pour le paiement.")

    if not 6 <= len(phone) <= 15:
        raise HTTPException(400, "Numéro invalide : entre ton numéro Mobile Money.")

    # JessiKaPay prélève 6 % sur ce que NexMarket reçoit : on majore pour que
    # le NET couvre le prix. L'acheteur voit ses frais sur la page de paiement.
    price = Decimal(str(listing.price))
    rate = Decimal(str(settings.JESSIKAPAY_COMMISSION_RATE))
    amount = (price / (Decimal(1) - rate)).to_integral_value(rounding=ROUND_CEILING)
    commission, net = split_deposit(amount)
    reference = "BUY-" + uuid4().hex[:20].upper()

    try:
        provider = await jessikapay_service.create_deposit(
            telegram_id=user.telegram_id,
            name=user.first_name or user.username or "NexMarket",
            country=country,
            phone=phone,
            amount=int(amount),
            reference=reference,
        )
    except MoneyFusionError as exc:
        raise HTTPException(502, str(exc)) from exc

    dep = Deposit(
        user_id=user.id,
        reference=reference,
        amount=amount,
        currency="XAF",
        phone=phone,
        country=country,
        purpose="purchase",
        listing_id=listing.id,
        jessikapay_request_id=provider["token"],
        jessikapay_code=None,
        payment_link=provider["url"],
        commission_amount=commission,
        net_amount_credited=net,
        status="pending",
        expires_at=None,
    )

    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    return {
        "id": dep.id,
        "reference": dep.reference,
        "amount": float(dep.amount),
        "price": float(price),
        "status": dep.status,
        "payment_link": dep.payment_link,
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
    Vérifie auprès de MoneyFusion si le dépôt est payé et crédite
    le wallet le cas échéant.
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
    """Estimation des frais (déduits du montant payé) ; le net exact est confirmé par MoneyFusion."""

    return {
        "commission_rate": settings.JESSIKAPAY_COMMISSION_RATE,
        "user_fee_rate": 0,
        "estimate": True,
    }


@router.get("/countries")
async def deposit_countries():
    """Pays disponibles pour un dépôt (liste MoneyFusion, devise CFA)."""

    return {
        "countries": [
            {"code": c["code"], "name": c["name"], "dial": c["dial"]}
            for c in await _deposit_countries()
        ]
    }
