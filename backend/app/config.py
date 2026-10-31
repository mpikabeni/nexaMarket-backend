from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "NexMarket"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"

    FRONTEND_URL: str = "https://nexamarketf.netlify.app"

    DATABASE_URL: str

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""

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
    JESSIKAPAY_WEBHOOK_URL: str = ""

    # Secret partagé qui authentifie les webhooks entrants.
    # À envoyer par JessiKaPay dans l'en-tête X-Webhook-Secret
    # (ou en paramètre ?token=... de l'URL du webhook).
    JESSIKAPAY_WEBHOOK_SECRET: str = ""
    NEXA_JP_NUMBER: str = ""

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
