from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "NexMarket"
    APP_VERSION: str = "1.0.11"
    ENVIRONMENT: str = "production"

    FRONTEND_URL: str = "https://nexamarketf.netlify.app"

    DATABASE_URL: str

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # URL publique de l'API (ex. https://nexamarket-backend-ffea.onrender.com).
    # Render fournit déjà RENDER_EXTERNAL_URL : utilisée si vide.
    PUBLIC_URL: str = ""

    # ========================================================
    # CANAL OBLIGATOIRE (le bot n'est utilisable qu'après l'avoir rejoint)
    # ========================================================
    # Le bot doit être ADMINISTRATEUR de ce canal pour pouvoir vérifier
    # l'abonnement des utilisateurs.

    REQUIRED_CHANNEL: str = "@Nexa_CG"
    REQUIRED_CHANNEL_URL: str = "https://t.me/Nexa_CG"

    # Mini App : l'utilisateur doit d'abord avoir démarré le bot (/start) ET
    # être membre du canal ci-dessus. Mettre "false" sur Render pour couper
    # temporairement cette obligation (tests).
    REQUIRE_BOT_AND_CHANNEL: bool = True

    # ========================================================
    # ADMIN
    # ========================================================

    ADMIN_CODE: str = ""
    ADMIN_TELEGRAM_ID: int = 0

    # ========================================================
    # SECURITY
    # ========================================================

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080

    # ========================================================
    # NEXMARKET
    # ========================================================

    NEXMARKET_FEE_RATE: float = 0.05

    SUPPORTED_CURRENCIES: str = "XAF,XOF,USD,EUR"

    # ========================================================
    # JESSIKAPAY
    # ========================================================

    JESSIKAPAY_API_URL: str = (
        "https://preferred-antonia-youtub-c1a62de8.koyeb.app"
    )

    JESSIKAPAY_API_KEY: str = ""
    JESSIKAPAY_API_SECRET: str = ""
    NEXA_JP_NUMBER: str = ""

    # Montant minimum d'un retrait (XAF).
    MIN_WITHDRAWAL_XAF: int = 1000

    # ========================================================
    # TELEGRAM AUTH
    # ========================================================

    TELEGRAM_AUTH_MAX_AGE_SECONDS: int = 86400

    # ========================================================
    # ESCROW
    # ========================================================

    ESCROW_PROTECTION_MINUTES: int = 60

    # Une transaction non payée au-delà de ce délai est annulée
    # et l'annonce est remise en vente.
    PENDING_PAYMENT_TTL_MINUTES: int = 120

    # ========================================================
    # CORS
    # ========================================================

    CORS_ORIGINS: str = ""

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_strong(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError(
                "JWT_SECRET doit contenir au moins 32 caractères."
            )
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Une variable Render laissée vide ("") valait "" et faisait
        # planter les champs numériques (ex. ADMIN_TELEGRAM_ID: int).
        env_ignore_empty=True,
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins_list(self):
        vals = [
            x.strip()
            for x in self.CORS_ORIGINS.split(",")
            if x.strip()
        ]

        if (
            self.FRONTEND_URL
            and self.FRONTEND_URL.rstrip("/") not in vals
        ):
            vals.append(self.FRONTEND_URL.rstrip("/"))

        return vals

    def get_supported_currencies(self):
        return [
            x.strip().upper()
            for x in self.SUPPORTED_CURRENCIES.split(",")
            if x.strip()
        ]


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
