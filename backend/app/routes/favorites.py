# backend/app/routes/favorites.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.favorite import Favorite
from app.models.listing import Listing
from app.models.user import User


router = APIRouter(
    prefix="/favorites",
    tags=["Favorites"],
)


# =========================================================
# UTILITAIRE
# =========================================================

def favorite_to_dict(favorite: Favorite) -> dict:
    return {
        "id": favorite.id,
        "user_id": favorite.user_id,
        "listing_id": favorite.listing_id,
        "created_at": favorite.created_at,
    }


# =========================================================
# LISTE DES FAVORIS
# =========================================================

@router.get("")
def get_my_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    favorites = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )

    return {
        "favorites": [
            favorite_to_dict(favorite)
            for favorite in favorites
        ],
        "total": len(favorites),
    }


# =========================================================
# VERIFIER SI UNE ANNONCE EST FAVORITE
# =========================================================

@router.get("/{listing_id}/status")
def favorite_status(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    favorite = (
        db.query(Favorite)
        .filter(
            Favorite.user_id == current_user.id,
            Favorite.listing_id == listing_id,
        )
        .first()
    )

    return {
        "listing_id": listing_id,
        "is_favorite": favorite is not None,
        "favorite_id": favorite.id if favorite else None,
    }


# =========================================================
# AJOUTER AUX FAVORIS
# =========================================================

@router.post("/{listing_id}")
def add_favorite(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    # Un vendeur ne peut pas ajouter sa propre annonce
    if listing.seller_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas ajouter votre propre annonce aux favoris.",
        )

    existing = (
        db.query(Favorite)
        .filter(
            Favorite.user_id == current_user.id,
            Favorite.listing_id == listing_id,
        )
        .first()
    )

    if existing:
        return {
            "status": "already_exists",
            "message": "Cette annonce est déjà dans vos favoris.",
            "favorite": favorite_to_dict(existing),
        }

    favorite = Favorite(
        user_id=current_user.id,
        listing_id=listing_id,
    )

    db.add(favorite)
    db.commit()
    db.refresh(favorite)

    return {
        "status": "created",
        "message": "Annonce ajoutée aux favoris.",
        "favorite": favorite_to_dict(favorite),
    }


# =========================================================
# RETIRER DES FAVORIS
# =========================================================

@router.delete("/{listing_id}")
def remove_favorite(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    favorite = (
        db.query(Favorite)
        .filter(
            Favorite.user_id == current_user.id,
            Favorite.listing_id == listing_id,
        )
        .first()
    )

    if not favorite:
        return {
            "status": "not_found",
            "message": "Cette annonce n'est pas dans vos favoris.",
        }

    db.delete(favorite)
    db.commit()

    return {
        "status": "deleted",
        "message": "Annonce retirée des favoris.",
    }


# =========================================================
# SUPPRIMER TOUS LES FAVORIS
# =========================================================

@router.delete("")
def clear_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted_count = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id)
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "status": "deleted",
        "message": "Tous les favoris ont été supprimés.",
        "deleted_count": deleted_count,
    }