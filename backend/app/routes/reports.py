from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.report import Report
from app.models.transaction import Transaction
from app.models.schemas import ReportCreate


router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)


# ============================================================
# HELPERS
# ============================================================

async def get_transaction(
    transaction_id: int,
    db: DBSession,
) -> Transaction:

    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id
        )
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction introuvable.",
        )

    return transaction


# ============================================================
# CREATE REPORT / DISPUTE
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    payload: ReportCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Crée un signalement lié à une transaction.

    Seuls l'acheteur et le vendeur peuvent signaler
    leur propre transaction.
    """

    transaction = await get_transaction(
        payload.transaction_id,
        db,
    )

    # --------------------------------------------------------
    # Vérifier que l'utilisateur participe
    # --------------------------------------------------------

    if (
        transaction.buyer_id != current_user.id
        and transaction.seller_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Vous ne participez pas à cette transaction."
            ),
        )

    # --------------------------------------------------------
    # Validation du motif
    # --------------------------------------------------------

    reason = (
        payload.reason.strip()
        if payload.reason
        else ""
    )

    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le motif du signalement est obligatoire.",
        )

    if len(reason) > 5000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le motif ne peut pas dépasser "
                "5000 caractères."
            ),
        )

    # --------------------------------------------------------
    # Vérifier les signalements déjà ouverts
    # --------------------------------------------------------

    result = await db.execute(
        select(Report).where(
            Report.transaction_id
            == transaction.id,
            Report.reporter_id
            == current_user.id,
            Report.status.in_(
                [
                    "pending",
                    "investigating",
                ]
            ),
        )
    )

    existing_report = result.scalar_one_or_none()

    if existing_report is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Vous avez déjà un signalement ouvert "
                "pour cette transaction."
            ),
        )

    # --------------------------------------------------------
    # Créer le signalement
    # --------------------------------------------------------

    report = Report(
        transaction_id=transaction.id,
        reporter_id=current_user.id,
        report_type=payload.report_type,
        reason=reason,
        status="pending",
    )

    db.add(report)

    # Si ce signalement devient le litige principal
    # de la transaction, on conserve aussi son état.
    if transaction.status not in {
        "completed",
        "cancelled",
        "refunded",
    }:
        transaction.status = "disputed"
        transaction.dispute_reason = reason
        transaction.disputed_at = (
            datetime.now(timezone.utc)
        )

    await db.commit()
    await db.refresh(report)

    return {
        "id": report.id,
        "transaction_id": report.transaction_id,
        "reporter_id": report.reporter_id,
        "report_type": report.report_type,
        "reason": report.reason,
        "status": report.status,
        "created_at": report.created_at,
    }


# ============================================================
# MY REPORTS
# ============================================================

@router.get(
    "/mine",
)
async def get_my_reports(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les signalements créés par l'utilisateur.
    """

    result = await db.execute(
        select(Report)
        .where(
            Report.reporter_id
            == current_user.id
        )
        .order_by(
            Report.created_at.desc()
        )
    )

    reports = result.scalars().all()

    return {
        "reports": [
            {
                "id": report.id,
                "transaction_id": report.transaction_id,
                "report_type": report.report_type,
                "reason": report.reason,
                "status": report.status,
                "admin_resolution": (
                    report.admin_resolution
                ),
                "resolved_at": report.resolved_at,
                "created_at": report.created_at,
            }
            for report in reports
        ]
    }


# ============================================================
# GET SINGLE REPORT
# ============================================================

@router.get(
    "/{report_id}",
)
async def get_report(
    report_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne un signalement à son auteur ou à un admin.
    """

    result = await db.execute(
        select(Report).where(
            Report.id == report_id
        )
    )

    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signalement introuvable.",
        )

    if (
        report.reporter_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé.",
        )

    return {
        "id": report.id,
        "transaction_id": report.transaction_id,
        "reporter_id": report.reporter_id,
        "report_type": report.report_type,
        "reason": report.reason,
        "status": report.status,
        "assigned_admin_id": (
            report.assigned_admin_id
        ),
        "admin_resolution": (
            report.admin_resolution
        ),
        "resolved_at": report.resolved_at,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


# ============================================================
# ADMIN - LIST REPORTS
# ============================================================

@router.get(
    "/admin/all",
)
async def get_all_reports(
    current_user: CurrentUser,
    db: DBSession,
    report_status: str | None = None,
):
    """
    Retourne les signalements pour les administrateurs.
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrateur requis.",
        )

    query = select(Report)

    if report_status:
        query = query.where(
            Report.status == report_status
        )

    query = query.order_by(
        Report.created_at.desc()
    )

    result = await db.execute(query)

    reports = result.scalars().all()

    return {
        "reports": [
            {
                "id": report.id,
                "transaction_id": report.transaction_id,
                "reporter_id": report.reporter_id,
                "report_type": report.report_type,
                "reason": report.reason,
                "status": report.status,
                "assigned_admin_id": (
                    report.assigned_admin_id
                ),
                "admin_resolution": (
                    report.admin_resolution
                ),
                "resolved_at": report.resolved_at,
                "created_at": report.created_at,
                "updated_at": report.updated_at,
            }
            for report in reports
        ],
        "count": len(reports),
    }


# ============================================================
# ADMIN - ASSIGN REPORT
# ============================================================

@router.post(
    "/{report_id}/assign",
)
async def assign_report(
    report_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Assigne un signalement à l'administrateur connecté.
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrateur requis.",
        )

    result = await db.execute(
        select(Report).where(
            Report.id == report_id
        )
    )

    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signalement introuvable.",
        )

    if report.status in {
        "resolved",
        "rejected",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Ce signalement est déjà clôturé."
            ),
        )

    report.assigned_admin_id = current_user.id
    report.status = "investigating"

    await db.commit()
    await db.refresh(report)

    return {
        "status": "success",
        "report_id": report.id,
        "assigned_admin_id": (
            report.assigned_admin_id
        ),
        "report_status": report.status,
    }


# ============================================================
# ADMIN - RESOLVE REPORT
# ============================================================

@router.patch(
    "/{report_id}/resolve",
)
async def resolve_report(
    report_id: int,
    resolution: str,
    current_user: CurrentUser,
    db: DBSession,
    result_status: str = "resolved",
):
    """
    Résout ou rejette un signalement.

    result_status :
    - resolved
    - rejected
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrateur requis.",
        )

    if result_status not in {
        "resolved",
        "rejected",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le statut doit être 'resolved' "
                "ou 'rejected'."
            ),
        )

    cleaned_resolution = (
        resolution.strip()
        if resolution
        else ""
    )

    if not cleaned_resolution:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La résolution est obligatoire.",
        )

    result = await db.execute(
        select(Report).where(
            Report.id == report_id
        )
    )

    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signalement introuvable.",
        )

    report.status = result_status
    report.assigned_admin_id = current_user.id
    report.admin_resolution = cleaned_resolution
    report.resolved_at = (
        datetime.now(timezone.utc)
    )

    await db.commit()
    await db.refresh(report)

    return {
        "status": "success",
        "report_id": report.id,
        "report_status": report.status,
        "admin_resolution": (
            report.admin_resolution
        ),
        "resolved_at": report.resolved_at,
    }
