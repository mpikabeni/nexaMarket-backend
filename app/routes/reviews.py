from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.review import Review
from app.models.transaction import Transaction
from app.models.schemas import ReviewCreate


router = APIRouter(
    prefix="/reviews",
    tags=["Reviews"],
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
# CREATE REVIEW
# ============================================================

@router.post(
    "/transaction/{transaction_id}",
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    transaction_id: int,
    payload: ReviewCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Permet à l'acheteur ou au vendeur de laisser une
    évaluation après une transaction terminée.

    Un utilisateur ne peut évaluer qu'une seule fois
    pour une même transaction.
    """

    transaction = await get_transaction(
        transaction_id,
        db,
    )

    # --------------------------------------------------------
    # Transaction terminée uniquement
    # --------------------------------------------------------

    if transaction.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Une évaluation peut uniquement être "
                "créée après la fin de la transaction."
            ),
        )

    # --------------------------------------------------------
    # Vérifier la participation
    # --------------------------------------------------------

    if current_user.id == transaction.buyer_id:
        reviewed_user_id = transaction.seller_id

    elif current_user.id == transaction.seller_id:
        reviewed_user_id = transaction.buyer_id

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Vous ne participez pas à cette transaction."
            ),
        )

    # --------------------------------------------------------
    # Vérifier le nombre d'évaluations
    # --------------------------------------------------------

    result = await db.execute(
        select(Review).where(
            Review.transaction_id == transaction_id,
            Review.reviewer_id == current_user.id,
        )
    )

    existing_review = result.scalar_one_or_none()

    if existing_review is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Vous avez déjà évalué cette transaction."
            ),
        )

    # --------------------------------------------------------
    # Validation de la note
    # --------------------------------------------------------

    if payload.rating < 1 or payload.rating > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La note doit être comprise entre 1 et 5.",
        )

    # --------------------------------------------------------
    # Validation du commentaire
    # --------------------------------------------------------

    comment = (
        payload.comment.strip()
        if payload.comment
        else None
    )

    if comment and len(comment) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le commentaire ne peut pas dépasser "
                "2000 caractères."
            ),
        )

    # --------------------------------------------------------
    # Création
    # --------------------------------------------------------

    review = Review(
        transaction_id=transaction.id,
        reviewer_id=current_user.id,
        reviewed_user_id=reviewed_user_id,
        rating=payload.rating,
        comment=comment,
        is_visible=True,
    )

    db.add(review)

    await db.commit()
    await db.refresh(review)

    return {
        "id": review.id,
        "transaction_id": review.transaction_id,
        "reviewer_id": review.reviewer_id,
        "reviewed_user_id": review.reviewed_user_id,
        "rating": review.rating,
        "comment": review.comment,
        "is_visible": review.is_visible,
        "created_at": review.created_at,
    }


# ============================================================
# GET REVIEWS RECEIVED BY USER
# ============================================================

@router.get(
    "/user/{user_id}",
)
async def get_user_reviews(
    user_id: int,
    db: DBSession,
):
    """
    Retourne uniquement les évaluations visibles
    reçues par un utilisateur.

    Les informations privées du reviewer ne sont pas
    exposées.
    """

    result = await db.execute(
        select(Review)
        .where(
            Review.reviewed_user_id == user_id,
            Review.is_visible.is_(True),
        )
        .order_by(
            Review.created_at.desc()
        )
    )

    reviews = result.scalars().all()

    return {
        "user_id": user_id,
        "reviews": [
            {
                "id": review.id,
                "transaction_id": review.transaction_id,
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at,
            }
            for review in reviews
        ],
    }


# ============================================================
# GET MY REVIEWS
# ============================================================

@router.get(
    "/mine",
)
async def get_my_reviews(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les évaluations données par l'utilisateur
    connecté.
    """

    result = await db.execute(
        select(Review)
        .where(
            Review.reviewer_id == current_user.id
        )
        .order_by(
            Review.created_at.desc()
        )
    )

    reviews = result.scalars().all()

    return {
        "reviews": [
            {
                "id": review.id,
                "transaction_id": review.transaction_id,
                "reviewed_user_id": review.reviewed_user_id,
                "rating": review.rating,
                "comment": review.comment,
                "is_visible": review.is_visible,
                "created_at": review.created_at,
            }
            for review in reviews
        ]
    }


# ============================================================
# ADMIN MODERATION
# ============================================================

@router.patch(
    "/{review_id}/visibility",
)
async def moderate_review(
    review_id: int,
    visible: bool,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Permet à un administrateur de masquer ou réafficher
    une évaluation.
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrateur requis.",
        )

    result = await db.execute(
        select(Review).where(
            Review.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Évaluation introuvable.",
        )

    review.is_visible = visible
    review.moderated_by_admin_id = current_user.id

    from datetime import datetime, timezone

    review.moderated_at = datetime.now(
        timezone.utc
    )

    await db.commit()
    await db.refresh(review)

    return {
        "status": "success",
        "review_id": review.id,
        "is_visible": review.is_visible,
        "moderated_by_admin_id": (
            review.moderated_by_admin_id
        ),
        "moderated_at": review.moderated_at,
    }
