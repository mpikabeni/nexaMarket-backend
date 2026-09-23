from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas import DepositRequest, WithdrawRequest
from app.services.wallet_service import wallet_service
from app.services.moneyfusion_service import MoneyFusionError


router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
)


# =========================================================
# UTILITAIRE
# =========================================================

def generate_reference(prefix: str) -> str:
    return (
        f"{prefix}-"
        f"{secrets.token_hex(8).upper()}"
    )


# =========================================================
# SOLDE
# =========================================================

@router.get("")
async def get_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne :
    - solde disponible
    - solde bloqué
    - revenus
    """

    return await wallet_service.get_balance(
        db=db,
        user_id=current_user.id,
    )


# =========================================================
# DEPOT
# =========================================================

@router.post("/deposit")
async def deposit(
    payload: DepositRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crée une session de paiement Money Fusion.

    IMPORTANT :
    Le solde n'est pas crédité ici.

    Il sera crédité uniquement après confirmation
    du paiement Money Fusion.
    """

    reference = generate_reference("DEP")

    try:
        result = await wallet_service.create_deposit(
            db=db,
            user_id=current_user.id,
            amount=payload.amount,
            customer_name=(
                current_user.first_name
                or current_user.username
                or "Client NexMarket"
            ),
            customer_phone=payload.phone,
            reference=reference,
        )

        await db.commit()

    except MoneyFusionError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        await db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Impossible de créer le dépôt.",
        ) from exc

    payment = result.get(
        "payment",
        {},
    )

    return {
        "status": "pending",
        "reference": reference,
        "token": result.get("token"),
        "amount": result.get("amount"),
        "checkout_url": payment.get("url"),
        "message": (
            "Paiement créé. "
            "Effectuez le paiement pour créditer "
            "votre portefeuille."
        ),
    }


# =========================================================
# VERIFICATION D'UN DEPOT
# =========================================================

@router.get("/deposit/status/{token}")
async def deposit_status(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Vérifie le statut d'un paiement Money Fusion.

    Cette route vérifie le paiement mais ne crédite pas
    automatiquement le portefeuille.

    Le webhook Money Fusion sera la source principale
    de confirmation et devra être idempotent.
    """

    reference = generate_reference("CHECK")

    try:
        result = await wallet_service.verify_deposit(
            db=db,
            user_id=current_user.id,
            token=token,
            reference=reference,
        )

    except MoneyFusionError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return result


# =========================================================
# RETRAIT
# =========================================================

@router.post("/withdraw")
async def withdraw(
    payload: WithdrawRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Demande de retrait via Money Fusion.

    Les fonds sont réservés avant l'appel à Money Fusion.
    Si Money Fusion refuse immédiatement la demande,
    ils sont remis dans le solde disponible.
    """

    reference = generate_reference("WDR")

    try:
        result = await wallet_service.request_withdrawal(
            db=db,
            user_id=current_user.id,
            amount=payload.amount,
            country_code=payload.country_code,
            phone=payload.phone,
            withdraw_mode=payload.withdraw_mode,
            reference=reference,
        )

        await db.commit()

    except MoneyFusionError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        await db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Impossible de créer le retrait.",
        ) from exc

    return {
        "status": "pending",
        "reference": reference,
        "amount": result.get("amount"),
        "withdrawal": result.get("withdrawal"),
        "message": (
            "Votre demande de retrait a été envoyée "
            "à Money Fusion."
        ),
    }


# =========================================================
# METHODES DE RETRAIT MONEY FUSION
# =========================================================

@router.get("/withdraw/methods")
async def withdraw_methods(
    current_user: User = Depends(get_current_user),
):
    """
    Retourne les méthodes de retrait disponibles
    chez Money Fusion.
    """

    try:
        return await wallet_service.moneyfusion_service.get_withdraw_methods()

    except AttributeError:
        # Fallback propre si l'instance Money Fusion
        # n'est pas exposée directement par wallet_service.
        from app.services.moneyfusion_service import (
            moneyfusion_service,
        )

        try:
            return await moneyfusion_service.get_withdraw_methods()

        except MoneyFusionError as exc:
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

    except MoneyFusionError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


# =========================================================
# WEBHOOK MONEY FUSION - PAYIN
# =========================================================

@router.post("/moneyfusion/webhook")
async def moneyfusion_webhook(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook Payin Money Fusion.

    Cette route ne fait PAS confiance aveuglément
    à l'événement reçu.

    Le token Money Fusion doit être vérifié auprès
    de Money Fusion avant de créditer le portefeuille.
    """

    from app.services.moneyfusion_service import (
        moneyfusion_service,
    )

    token = (
        moneyfusion_service.extract_payment_token(
            payload
        )
    )

    if not token:
        return {
            "status": "ignored",
            "reason": "token_missing",
        }

    # Vérification réelle auprès de Money Fusion.
    try:
        status_data = (
            await moneyfusion_service.get_payment_status(
                token
            )
        )

    except MoneyFusionError:
        raise HTTPException(
            status_code=502,
            detail=(
                "Impossible de vérifier le paiement "
                "auprès de Money Fusion."
            ),
        )

    status = (
        moneyfusion_service.extract_payment_status(
            status_data
        )
    )

    if status != "paid":
        return {
            "status": "ignored",
            "payment_status": status,
        }

    amount = (
        moneyfusion_service.extract_payment_amount(
            status_data
        )
    )

    if not amount:
        return {
            "status": "ignored",
            "reason": "amount_missing",
        }

    # -----------------------------------------------------
    # IMPORTANT
    # -----------------------------------------------------
    #
    # L'association token -> dépôt doit être ajoutée
    # dans une table de paiements/dépôts dédiée.
    #
    # Nous ne créditons donc PAS le portefeuille ici
    # tant que cette association n'existe pas.
    #
    # Cela évite de créditer le mauvais compte.
    #

    return {
        "status": "verified",
        "payment_status": "paid",
        "token": token,
        "amount": amount,
        "message": (
            "Paiement vérifié. "
            "Association avec le portefeuille "
            "à finaliser."
        ),
    }