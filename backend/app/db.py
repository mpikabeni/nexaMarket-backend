from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def normalize_database_url(url: str) -> str:
    """
    Convertit une URL PostgreSQL classique vers asyncpg.
    """

    if url.startswith("postgresql+asyncpg://"):
        return url

    if url.startswith("postgresql+psycopg://"):
        return url.replace(
            "postgresql+psycopg://",
            "postgresql+asyncpg://",
            1,
        )

    if url.startswith("postgresql://"):
        return url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    return url


DATABASE_URL = normalize_database_url(
    settings.DATABASE_URL
)


# =========================================================
# SQLALCHEMY ENGINE
# =========================================================

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
)


# =========================================================
# SESSION FACTORY
# =========================================================

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# =========================================================
# BASE MODEL
# =========================================================

class Base(DeclarativeBase):
    pass


# =========================================================
# DATABASE DEPENDENCY
# =========================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Fournit une session PostgreSQL à chaque requête.

    En cas d'erreur, la transaction est annulée.
    """

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# =========================================================
# INITIALISATION
# =========================================================

async def init_db() -> None:
    """
    Initialise les tables connues par SQLAlchemy.

    Les imports ci-dessous sont volontairement effectués
    avant create_all afin d'enregistrer les modèles.
    """

    from app.models import channel
    from app.models import favorite
    from app.models import listing
    from app.models import message
    from app.models import plateform
    from app.models import report
    from app.models import review
    from app.models import transaction
    from app.models import user
    from app.models import wallet

    _ = (
        channel,
        favorite,
        listing,
        message,
        plateform,
        report,
        review,
        transaction,
        user,
        wallet,
    )

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all
        )


# =========================================================
# FERMETURE
# =========================================================

async def close_db() -> None:
    """
    Ferme proprement le pool de connexions.
    """

    await engine.dispose()
