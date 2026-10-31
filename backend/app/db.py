from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def normalize_database_url(url: str) -> tuple[str, dict]:
    """
    Convertit une URL PostgreSQL classique vers asyncpg.

    - postgres:// et postgresql:// -> postgresql+asyncpg://
    - asyncpg REFUSE le paramètre `?sslmode=...` (TypeError au premier
      accès à la base) : il est retiré et converti en option SSL.
    """

    url = (url or "").strip()

    for prefix in (
        "postgresql+psycopg://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break

    connect_args: dict = {}

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    sslmode = query.pop("sslmode", None)

    if sslmode and sslmode != "disable":
        connect_args["ssl"] = "require"

    if sslmode is not None:
        url = urlunsplit(
            parts._replace(query=urlencode(query))
        )

    return url, connect_args


DATABASE_URL, _CONNECT_ARGS = normalize_database_url(
    settings.DATABASE_URL
)

# =========================================================
# SQLALCHEMY ENGINE
# =========================================================

engine = create_async_engine(
    DATABASE_URL,
    connect_args=_CONNECT_ARGS,
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
    from app.models import platform
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
        platform,
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
