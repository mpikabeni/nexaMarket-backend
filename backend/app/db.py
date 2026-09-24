# backend/app/db.py

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


# =========================================================
# DATABASE URL
# =========================================================

DATABASE_URL = settings.DATABASE_URL

# Render/PostgreSQL peut fournir une URL commençant par
# postgres://. SQLAlchemy moderne utilise postgresql+psycopg://.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )

elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )


# =========================================================
# ENGINE
# =========================================================

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)


# =========================================================
# SESSION
# =========================================================

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# =========================================================
# BASE MODEL
# =========================================================

class Base(DeclarativeBase):
    pass


# =========================================================
# DATABASE DEPENDENCY
# =========================================================

def get_db() -> Generator[Session, None, None]:
    """
    Fournit une session PostgreSQL à chaque requête FastAPI.
    La session est automatiquement fermée à la fin de la requête.
    """

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# =========================================================
# INITIALISATION
# =========================================================

def init_db() -> None:
    """
    Crée les tables définies dans les modèles.

    Cette fonction est surtout utile pour le premier déploiement.
    """

    # Les imports doivent être faits ici afin que SQLAlchemy
    # connaisse tous les modèles avant create_all().
    from app.models.user import User
    from app.models.channel import Channel
    from app.models.listings import Listing
    from app.models.wallet import Wallet
    from app.models.transaction import Transaction
    from app.models.message import Message
    from app.models.favorite import Favorite
    from app.models.review import Review
    from app.models.report import Report
    from app.models.platform import PlatformWallet, PlatformLedger

    # Évite les avertissements de linters concernant les imports
    # utilisés uniquement pour enregistrer les modèles.
    _ = (
        User,
        Channel,
        Listing,
        Wallet,
        Transaction,
        Message,
        Favorite,
        Review,
        Report,
        PlatformWallet,
        PlatformLedger,
    )

    Base.metadata.create_all(bind=engine)
