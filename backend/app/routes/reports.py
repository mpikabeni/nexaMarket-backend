# ============================================================
# NEXMARKET
# backend/app/routes/reports.py
# ============================================================

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.listing import Listing
from app.models.transaction import Transaction
from app.models.report import Report
from app.schemas import ReportCreate, ReportResponse


router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)


# ============================================================
# HELPERS
# ============================================================

def get_listing(
    listing_id: int,
    db: Session,
) -> Listing:

    listing = (
        db.query(Listing)
        .filter(Listing.id == listing_id)
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    return listing


def get_transaction(
    transaction_id: int,
    db: Session,
) -> Transaction:

    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    return transaction


# ============================================================
# CREER UN SIGNALEMENT
# ============================================================

@router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    payload: ReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    if not payload.listing_id and not payload.transaction_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Vous devez indiquer une annonce "
                "ou une transaction."
            ),
        )

    listing = None
    transaction = None

    # --------------------------------------------------------
    # Vérification annonce
    # --------------------------------------------------------

    if payload.listing_id:

        listing = get_listing(
            payload.listing_id,
            db,
        )

    # --------------------------------------------------------
    # Vérification transaction
    # --------------------------------------------------------

    if payload.transaction_id:

        transaction = get_transaction(
            payload.transaction_id,
            db,
        )

        # Une transaction ne peut être signalée que
        # par l'acheteur, le vendeur ou un administrateur.
        if (
            transaction.buyer_id != current_user.id
            and transaction.seller_id != current_user.id
            and not current_user.is_admin
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Vous n'avez pas accès à cette transaction."
                ),
            )

    # --------------------------------------------------------
    # Eviter les doublons évidents
    # --------------------------------------------------------

    existing_query = (
        db.query(Report)
        .filter(
            Report.reporter_id == current_user.id,
            Report.status.in_(
                [
                    "pending",
                    "reviewing",
                ]
            ),
        )
    )

    if payload.listing_id:
        existing_query = existing_query.filter(
            Report.listing_id == payload.listing_id
        )

    if payload.transaction_id:
        existing_query = existing_query.filter(
            Report.transaction_id == payload.transaction_id
        )

    existing = existing_query.first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Vous avez déjà un signalement "
                "en cours pour cet élément."
            ),
        )

    # --------------------------------------------------------
    # Création
    # --------------------------------------------------------

    reason = payload.reason.strip()

    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le motif du signalement est obligatoire.",
        )

    description = (
        payload.description.strip()
        if payload.description
        else None
    )

    report = Report(
        reporter_id=current_user.id,
        listing_id=(
            listing.id
            if listing
            else None
        ),
        transaction_id=(
            transaction.id
            if transaction
            else None
        ),
        reason=reason,
        description=description,
        status="pending",
        created_at=datetime.utcnow(),
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    return report


# ============================================================
# MES SIGNALEMENTS
# ============================================================

@router.get(
    "/mine",
    response_model=list[ReportResponse],
)
def get_my_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    reports = (
        db.query(Report)
        .filter(
            Report.reporter_id == current_user.id
        )
        .order_by(
            Report.created_at.desc()
        )
        .all()
    )

    return reports


# ============================================================
# DETAIL D'UN SIGNALEMENT
# ============================================================

@router.get(
    "/{report_id}",
    response_model=ReportResponse,
)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    report = (
        db.query(Report)
        .filter(Report.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signalement introuvable.",
        )

    # L'utilisateur voit uniquement ses signalements.
    # Les administrateurs peuvent voir tous les signalements.
    if (
        report.reporter_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé.",
        )

    return report


# ============================================================
# ANNULER UN SIGNALEMENT
# ============================================================

@router.post(
    "/{report_id}/cancel",
)
def cancel_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    report = (
        db.query(Report)
        .filter(Report.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signalement introuvable.",
        )

    if report.reporter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Vous ne pouvez pas modifier "
                "ce signalement."
            ),
        )

    if report.status not in {
        "pending",
        "reviewing",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Ce signalement ne peut plus être annulé."
            ),
        )

    report.status = "rejected"
    report.admin_note = "Signalement annulé par l'utilisateur."
    report.resolved_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "Signalement annulé.",
        "report_id": report.id,
        "status": report.status,
    }