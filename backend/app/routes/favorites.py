from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, delete

from app.deps import CurrentUser, DBSession
from app.models.favorite import Favorite
from app.models.listing import Listing
from app.models.schemas import FavoriteCreate


router = APIRouter(
    prefix="/favorites",
    tags=["Favorites"],
)


# ============================================================
# ADD FAVORITE
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def add_favorite(
    payload: FavoriteCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Ajoute une annonce aux favoris de l'utilisateur.
    """

    result = await db.execute(
        select(Listing).where(
            Listing.id == payload.listing_id
        )
    )

    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annonce introuvable.",
        )

    if not listing.is_public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette annonce n'est pas disponible.",
        )

    # Vérifier si elle est déjà dans les favoris
    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.listing_id == payload.listing_id,
        )
    )

    existing = result.scalar_one_or_none()

    if existing is not None:
        return {
            "status": "already_exists",
            "favorite_id": existing.id,
            "listing_id": existing.listing_id,
        }

    favorite = Favorite(
        user_id=current_user.id,
        listing_id=payload.listing_id,
    )

    db.add(favorite)

    await db.commit()
    await db.refresh(favorite)

    return {
        "status": "success",
        "favorite_id": favorite.id,
        "listing_id": favorite.listing_id,
        "created_at": favorite.created_at,
    }


# ============================================================
# GET MY FAVORITES
# ============================================================

@router.get(
    "",
)
async def get_my_favorites(
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retourne les annonces enregistrées dans les favoris.
    """

    result = await db.execute(
        select(Favorite, Listing)
        .join(
            Listing,
            Listing.id == Favorite.listing_id,
        )
        .where(
            Favorite.user_id == current_user.id
        )
        .order_by(
            Favorite.created_at.desc()
        )
    )

    rows = result.all()

    favorites = []

    for favorite, listing in rows:

        # Une annonce retirée de la publication reste
        # dans les favoris mais n'est pas considérée
        # comme disponible.
        favorites.append(
            {
                "favorite_id": favorite.id,
                "listing_id": listing.id,
                "title": listing.title,
                "description": listing.description,
                "category": listing.category,
                "price": listing.price,
                "currency": listing.currency,
                "status": listing.status,
                "is_public": listing.is_public,
                "published_at": listing.published_at,
                "created_at": favorite.created_at,
            }
        )

    return {
        "favorites": favorites,
        "count": len(favorites),
    }


# ============================================================
# CHECK FAVORITE
# ============================================================

@router.get(
    "/{listing_id}/check",
)
async def check_favorite(
    listing_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Vérifie si une annonce est dans les favoris.
    """

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.listing_id == listing_id,
        )
    )

    favorite = result.scalar_one_or_none()

    return {
        "listing_id": listing_id,
        "is_favorite": favorite is not None,
        "favorite_id": (
            favorite.id
            if favorite is not None
            else None
        ),
    }


# ============================================================
# REMOVE FAVORITE
# ============================================================

@router.delete(
    "/{listing_id}",
)
async def remove_favorite(
    listing_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retire une annonce des favoris.
    """

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.listing_id == listing_id,
        )
    )

    favorite = result.scalar_one_or_none()

    if favorite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cette annonce n'est pas dans vos favoris.",
        )

    await db.delete(favorite)
    await db.commit()

    return {
        "status": "success",
        "listing_id": listing_id,
        "removed": True,
    }


# ============================================================
# REMOVE FAVORITE BY ID
# ============================================================

@router.delete(
    "/id/{favorite_id}",
)
async def remove_favorite_by_id(
    favorite_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """
    Retire un favori à partir de son ID.
    """

    result = await db.execute(
        select(Favorite).where(
            Favorite.id == favorite_id
        )
    )

    favorite = result.scalar_one_or_none()

    if favorite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favori introuvable.",
        )

    if favorite.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce favori ne vous appartient pas.",
        )

    await db.delete(favorite)
    await db.commit()

    return {
        "status": "success",
        "favorite_id": favorite_id,
        "removed": True,
    }
