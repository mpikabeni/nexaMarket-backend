from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.services import money_notifications
from app.services.countries import local_phone
from app.services.moneyfusion import (
    MoneyFusionError,
    find_method,
    moneyfusion_service,
    public_catalog,
    to_local_amount,
)
from app.services.payout_settlement import fail_withdrawal
from app.services.wallet_service import (
    WalletService,
    WalletServiceError,
)


router = APIRouter(
    prefix="/withdrawals",
    tags=["Withdrawals"],
)


# ============================================================
# PAYS ET RÉSEAUX DISPONIBLES (source : MoneyFusion)
# ============================================================

@router.get("/methods")
async def withdrawal_methods(user: User = Depends(get_current_user)):
    """Pays + réseaux (MTN, Airtel, Orange, Wave...) où l'on peut retirer."""

    countries, source = await moneyfusion_service.get_countries()

    return {
        "countries": public_catalog(countries),
        "source": source,  # live | cache | fallback
        "min_amount": settings.MIN_WITHDRAWAL_XAF,
    }


# ============================================================
# CREATE WITHDRAWAL
# ============================================================

def _webhook_url() -> str:
    base = (settings.PUBLIC_URL or "").strip().rstrip("/")
    secret = (settings.MONEYFUSION_WEBHOOK_SECRET or "").strip()

    if not base or not secret:
        return ""

    return f"{base}/webhooks/moneyfusion/{secret}"


@router.post("")
async def request_withdrawal(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=410,
        detail="Les retraits manuels ne sont plus proposés : le vendeur est payé automatiquement.",
    )

    """
    Crée un retrait Mobile Money (MoneyFusion) : pays + réseau + numéro.

    Le montant est d'abord BLOQUÉ dans le wallet. MoneyFusion répond « accepté »
    avec un jeton ; le retrait reste « processing » jusqu'à ce que la tâche de
    fond (ou le webhook, vérifié par l'API) confirme le succès ou l'échec.
    """

    raw_amount = payload.get("amount", 0)
    country = str(payload.get("country", "")).strip().lower()
    method = str(payload.get("method", "")).strip()
    raw_phone = str(payload.get("phone", "")).strip()

    try:
        amount = Decimal(str(raw_amount))

        if not amount.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Montant invalide.")

    amount = amount.quantize(Decimal("0.01"))

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant doit être supérieur à zéro.")

    if amount != amount.to_integral_value():
        raise HTTPException(status_code=400, detail="Le montant doit être un nombre entier (XAF).")

    min_amount = Decimal(settings.MIN_WITHDRAWAL_XAF)

    if amount < min_amount:
        raise HTTPException(
            status_code=400,
            detail=(
                "Le montant minimum de retrait est de "
                f"{int(min_amount):,} XAF.".replace(",", " ")
            ),
        )

    # ========================================================
    # PAYS + RÉSEAU : vérifiés côté serveur contre la liste MoneyFusion
    # ========================================================

    countries, _source = await moneyfusion_service.get_countries()
    entry = find_method(countries, country, method)

    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="Ce pays ou ce réseau n'est pas disponible pour les retraits.",
        )

    local_amount = to_local_amount(amount, entry["currency"])

    if not local_amount or local_amount < 1:
        raise HTTPException(status_code=400, detail="Montant trop faible pour ce pays.")

    phone = local_phone(country.upper(), raw_phone)

    if not 6 <= len(phone) <= 15:
        raise HTTPException(
            status_code=400,
            detail="Numéro invalide : entre ton numéro Mobile Money du réseau choisi.",
        )

    # ========================================================
    # WALLET
    # ========================================================

    wallet_service = WalletService(db)

    try:
        wallet = await wallet_service.get_wallet(user.id)
    except WalletServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    available_balance = Decimal(str(wallet.available_balance or 0))

    if available_balance < amount:
        raise HTTPException(status_code=400, detail="Solde insuffisant.")

    # ========================================================
    # UNIQUE REFERENCE + BLOCAGE DES FONDS
    # ========================================================

    reference = f"WD-{user.id}-{uuid4().hex[:16].upper()}"

    try:
        await wallet_service.block(
            user_id=user.id,
            amount=amount,
            reference=reference,
            description="Fonds bloqués pour retrait Mobile Money",
        )
    except WalletServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    withdrawal = Withdrawal(
        user_id=user.id,
        reference=reference,
        amount=amount,
        currency="XAF",
        payout_country=country,
        payout_method=method,
        payout_phone=phone,
        payout_currency=entry["currency"],
        payout_amount=local_amount,
        status="pending",
    )

    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)

    # ========================================================
    # MONEYFUSION PAYOUT
    # ========================================================

    try:
        payout_response = await moneyfusion_service.withdraw(
            country=country,
            method=method,
            phone=phone,
            amount=local_amount,
            webhook_url=_webhook_url(),
        )

    except MoneyFusionError as exc:

        # Timeout / réseau / 5xx / réponse sans jeton : MoneyFusion a PEUT-ÊTRE
        # déjà payé. Rendre l'argent ici permettrait un double paiement. On
        # garde les fonds bloqués et un admin tranche
        # (POST /admin/withdrawals/{id}/resolve).
        if exc.ambiguous:
            withdrawal.status = "processing"
            withdrawal.processed_at = datetime.utcnow()
            withdrawal.failure_reason = f"Statut inconnu, à vérifier : {exc}"
            await db.commit()

            await money_notifications.withdrawal_processing(db, withdrawal, needs_admin=True)

            return {
                "success": True,
                "id": withdrawal.id,
                "reference": withdrawal.reference,
                "provider": "moneyfusion",
                "status": withdrawal.status,
                "message": (
                    "Votre retrait est en cours de vérification. "
                    "Le bot vous prévient dès la confirmation."
                ),
            }

        # Refus explicite : MoneyFusion n'a rien envoyé, on libère les fonds.
        await fail_withdrawal(db, withdrawal, str(exc))
        await money_notifications.withdrawal_failed(db, withdrawal, str(exc))

        raise HTTPException(status_code=502, detail=f"Retrait refusé : {exc}") from exc

    # ========================================================
    # ACCEPTÉ : jeton de suivi enregistré, le retrait reste « processing »
    # ========================================================

    withdrawal.jessikapay_transaction_id = payout_response["token"]
    withdrawal.status = "processing"
    withdrawal.processed_at = datetime.utcnow()
    withdrawal.failure_reason = None
    await db.commit()

    await money_notifications.withdrawal_processing(db, withdrawal, needs_admin=False)

    await db.refresh(withdrawal)

    return {
        "success": True,
        "id": withdrawal.id,
        "reference": withdrawal.reference,
        "provider": "moneyfusion",
        "amount": float(withdrawal.amount),
        "currency": withdrawal.currency,
        "payout_amount": float(withdrawal.payout_amount),
        "payout_currency": withdrawal.payout_currency,
        "status": withdrawal.status,
        "message": (
            "Votre retrait est en cours de traitement. "
            "Le bot vous prévient dès la confirmation."
        ),
    }


# ============================================================
# MY WITHDRAWALS
# ============================================================

@router.get("/mine")
async def mine(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Retourne les retraits de l'utilisateur connecté.
    """

    result = await db.execute(
        select(Withdrawal)
        .where(
            Withdrawal.user_id == user.id
        )
        .order_by(
            Withdrawal.created_at.desc()
        )
    )

    withdrawals = result.scalars().all()

    return [
        {
            "id": withdrawal.id,
            "reference": withdrawal.reference,
            "amount": float(
                withdrawal.amount
            ),
            "currency": withdrawal.currency,
            "status": withdrawal.status,
            "country": withdrawal.payout_country,
            "method": withdrawal.payout_method,
            "phone": withdrawal.payout_phone,
            "payout_amount": (
                float(withdrawal.payout_amount)
                if withdrawal.payout_amount is not None
                else None
            ),
            "payout_currency": withdrawal.payout_currency,
            "failure_reason": (
                withdrawal.failure_reason
            ),
            "created_at": (
                withdrawal.created_at.isoformat()
                if withdrawal.created_at
                else None
            ),
            "processed_at": (
                withdrawal.processed_at.isoformat()
                if withdrawal.processed_at
                else None
            ),
            "completed_at": (
                withdrawal.completed_at.isoformat()
                if withdrawal.completed_at
                else None
            ),
        }
        for withdrawal in withdrawals
    ]
