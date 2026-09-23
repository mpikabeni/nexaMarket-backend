# backend/app/config.py

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # =========================================================
    # APPLICATION
    # =========================================================

    APP_NAME: str = "NexMarket API"
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

    # Secret éventuel du webhook Telegram
    TELEGRAM_WEBHOOK_SECRET: str = ""


    # =========================================================
    # SECURITY
    # =========================================================

    JWT_SECRET: str

    JWT_ALGORITHM: str = "HS256"

    ADMIN_TOKEN_EXPIRE_MINUTES: int = 60

    # Code secret utilisé par l'interface admin
    ADMIN_CODE: str


    # =========================================================
    # NEXMARKET
    # =========================================================

    # Exemple :
    # 0.05 = 5 %
    #
    # À définir dans Render.
    NEXMARKET_FEE_RATE: float = 0.0

    # Frais de publication.
    # 0 = publication gratuite.
    LISTING_PUBLISH_FEE: float = 0.0

    DEFAULT_CURRENCY: str = "XAF"


    # =========================================================
    # MONEY FUSION
    # =========================================================

    # URL API fournie dans ton tableau de bord
    # Money Fusion.
    MONEYFUSION_API_URL: str = ""

    # URL appelée après le paiement
    MONEYFUSION_RETURN_URL: str = ""

    # URL webhook Money Fusion
    MONEYFUSION_PAYIN_WEBHOOK_URL: str = ""

    # Clé privée utilisée pour les retraits
    MONEYFUSION_API_KEY: str = ""

    # API de retrait Money Fusion
    MONEYFUSION_WITHDRAW_URL: str = (
        "https://pay.moneyfusion.net/api/v1/withdraw"
    )

    # Méthodes de retrait
    MONEYFUSION_WITHDRAW_METHODS_URL: str = (
        "https://pay.moneyfusion.net/api/v1/withdraw/methods"
    )

    # Webhook des retraits
    MONEYFUSION_PAYOUT_WEBHOOK_URL: str = ""

    # Vérification du statut d'un paiement
    MONEYFUSION_PAYMENT_STATUS_URL: str = (
        "https://pay.moneyfusion.net/paiementNotif"
    )


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


    # =========================================================
    # CORS LIST
    # =========================================================

    @property
    def cors_origins_list(self) -> list[str]:

        origins: list[str] = []

        if self.CORS_ORIGINS:

            origins.extend(
                origin.strip()
                for origin in self.CORS_ORIGINS.split(",")
                if origin.strip()
            )

        if self.FRONTEND_URL:

            frontend = self.FRONTEND_URL.rstrip("/")

            if frontend not in origins:
                origins.append(frontend)

        # Développement local
        local_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

        for origin in local_origins:

            if origin not in origins:
                origins.append(origin)

        return origins


# =========================================================
# SETTINGS INSTANCE
# =========================================================

@lru_cache
def get_settings() -> Settings:

    return Settings()


settings = get_settings()