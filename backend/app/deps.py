from collections.abc import AsyncGenerator, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, decode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.user import User


# ============================================================
# DATABASE
# ============================================================

DBSession = Annotated[AsyncSession, Depends(get_db)]


# ============================================================
# AUTHENTICATION
# ============================================================

bearer_scheme = HTTPBearer(
    auto_error=False,
)


async def get_current_user(
    db: DBSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User:
    """
    Récupère l'utilisateur connecté à partir du JWT.

    Le frontend doit envoyer :

        Authorization: Bearer <token>
    """

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        payload = decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant utilisateur invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.is_active.is_(True),
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable ou désactivé.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]


# ============================================================
# ADMIN
# ============================================================

async def get_current_admin(
    current_user: CurrentUser,
) -> User:
    """
    Autorise uniquement les comptes administrateurs NexMarket.
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès administrateur requis.",
        )

    return current_user


CurrentAdmin = Annotated[
    User,
    Depends(get_current_admin),
]


# ============================================================
# ADMIN ROLE CHECK
# ============================================================

def require_admin_role(*allowed_roles: str) -> Callable:
    """
    Prépare un contrôle de rôle administrateur.

    Exemple :

        Depends(require_admin_role("super_admin"))
    """

    async def dependency(
        current_user: CurrentAdmin,
    ) -> User:
        # Pour le moment le modèle User possède uniquement
        # is_admin. Les rôles détaillés pourront être ajoutés
        # plus tard sans modifier les routes existantes.

        if not allowed_roles:
            return current_user

        # Aucun champ role n'existe actuellement dans User.
        # On ne simule donc pas de rôle qui n'est pas stocké.
        return current_user

    return dependency


# ============================================================
# ACTIVE USER
# ============================================================

async def require_active_user(
    current_user: CurrentUser,
) -> User:
    """
    Vérification explicite qu'un compte est actif.
    """

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé.",
        )

    return current_user
