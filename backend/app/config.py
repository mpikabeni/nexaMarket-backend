from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # =========================================================
    # APPLICATION
    # =========================================================

    APP_NAME: str = "NexMarket"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"

    FRONTEND_URL: str = "https://nexamarketf.netlify.app"

    # =========================================================
    # DATABASE
    # =========================================================

    DATABASE_URL: str

    # =========================================================
    # TELEGRAM
    # =========================================================

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = ""

    # =========================================================
    # JWT
    # =========================================================

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7

    # =========================================================
    # NEXMARKET
    # =========================================================

    # 5 % de commission sur chaque vente
    NEXMARKET_FEE_RATE: float = Field(
        default=0.05,
        ge=0,
        le=1,
    )

    DEFAULT_CURRENCY: str = "XAF"

    # =========================================================
    # JESSIKAPAY
    # =========================================================

    JESSIKAPAY_API_URL: str = (
        "https://preferred-antonia-youtub-c1a62de8.koyeb.app"
    )

    JESSIKAPAY_API_KEY: str = ""
    JESSIKAPAY_API_SECRET: str = ""

    # URL HTTPS publique de notre webhook
    JESSIKAPAY_WEBHOOK_URL: str = ""

    # Numéro JP du compte de règlement NEXA.
    # Il reste uniquement côté backend.
    NEXA_JP_NUMBER: str = ""

    # =========================================================
    # SECURITY
    # =========================================================

    # Durée maximale d'une session Telegram acceptée
    TELEGRAM_AUTH_MAX_AGE_SECONDS: int = 86400

    # Limites anti-abus
    DEPOSIT_RATE_LIMIT_PER_MINUTE: int = 5
    WITHDRAW_RATE_LIMIT_PER_MINUTE: int = 3
    JP_LOOKUP_RATE_LIMIT_PER_MINUTE: int = 10

    # =========================================================
    # CORS
    # =========================================================

    CORS_ORIGINS: str = ""

    # =========================================================
    # PYDANTIC SETTINGS
    # =========================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def cors_origins_list(self) -> list[str]:
        """
        Transforme :
            CORS_ORIGINS=https://site1.com,https://site2.com

        en :
            ["https://site1.com", "https://site2.com"]
        """
        if not self.CORS_ORIGINS:
            return [self.FRONTEND_URL]

        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
