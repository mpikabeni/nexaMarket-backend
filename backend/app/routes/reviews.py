from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.review import Review
from app.models.transaction import Transaction
from app.schemas import ReviewCreate, ReviewResponse

router = APIRouter(prefix="/reviews", tags=["reviews"])


def can_access_transaction(transaction, user):
    return (
        user.is_admin
        or transaction.buyer_id == user.id
        or transaction.seller_id == user.id
    )


# =========================
# MES AVIS
# =========================

@router.get("/mine", response_model=list[ReviewResponse])
def get_my_reviews(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return (
        db.query(Review)
        .filter(Review.reviewer_id == current_user.id)
        .order_by(Review.created_at.desc())
        .all()
    )


# =========================
# AVIS D'UN UTILISATEUR
# =========================

@router.get("/user/{user_id}", response_model=list[ReviewResponse])
def get_user_reviews(
    user_id: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(Review)
        .filter(
            Review.reviewed_user_id == user_id,
            Review.is_visible.is_(True),
        )
        .order_by(Review.created_at.desc())
        .all()
    )


# =========================
# AVIS D'UNE TRANSACTION
# =========================

@router.get(
    "/transaction/{transaction_id}",
    response_model=list[ReviewResponse],
)
def get_transaction_reviews(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable",
        )

    if not can_access_transaction(transaction, current_user):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé",
        )

    return (
        db.query(Review)
        .filter(Review.transaction_id == transaction_id)
        .order_by(Review.created_at.desc())
        .all()
    )


# =========================
# CRÉER UN AVIS
# =========================

@router.post(
    "",
    response_model=ReviewResponse,
    status_code=201,
)
def create_review(
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    transaction = (
        db.query(Transaction)
        .filter(Transaction.id == payload.transaction_id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction introuvable",
        )

    if transaction.status != "completed":
        raise HTTPException(
            status_code=400,
            detail="Une évaluation est possible uniquement après une transaction terminée",
        )

    if current_user.id not in (
        transaction.buyer_id,
        transaction.seller_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Vous ne participez pas à cette transaction",
        )

    existing = (
        db.query(Review)
        .filter(
            Review.transaction_id == transaction.id,
            Review.reviewer_id == current_user.id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Vous avez déjà évalué cette transaction",
        )

    if current_user.id == transaction.buyer_id:
        reviewed_user_id = transaction.seller_id
    else:
        reviewed_user_id = transaction.buyer_id

    review = Review(
        transaction_id=transaction.id,
        reviewer_id=current_user.id,
        reviewed_user_id=reviewed_user_id,
        rating=payload.rating,
        comment=payload.comment,
        is_visible=True,
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    return review


# =========================
# MODIFIER UN AVIS
# =========================

@router.patch(
    "/{review_id}",
    response_model=ReviewResponse,
)
def update_review(
    review_id: int,
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    review = (
        db.query(Review)
        .filter(Review.id == review_id)
        .first()
    )

    if not review:
        raise HTTPException(
            status_code=404,
            detail="Évaluation introuvable",
        )

    if review.reviewer_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Vous ne pouvez modifier que votre évaluation",
        )

    if payload.transaction_id != review.transaction_id:
        raise HTTPException(
            status_code=400,
            detail="La transaction de l'évaluation ne peut pas être modifiée",
        )

    review.rating = payload.rating
    review.comment = payload.comment

    db.commit()
    db.refresh(review)

    return review


# =========================
# SUPPRIMER UN AVIS
# =========================

@router.delete("/{review_id}")
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    review = (
        db.query(Review)
        .filter(Review.id == review_id)
        .first()
    )

    if not review:
        raise HTTPException(
            status_code=404,
            detail="Évaluation introuvable",
        )

    if (
        review.reviewer_id != current_user.id
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="Vous ne pouvez pas supprimer cette évaluation",
        )

    db.delete(review)
    db.commit()

    return {
        "status": "success",
        "message": "Évaluation supprimée",
    }
