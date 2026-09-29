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

    FRONTEND_URL: str = "https://nexamarke.netlify.app"

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
    JWT_EXPIRE_MINUTES: int = 10080  # 7 jours

    # =========================================================
    # NEXMARKET
    # =========================================================

    # Commission prélevée sur chaque vente.
    # 5 % = 0.05
    NEXMARKET_FEE_RATE: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
    )

    # =========================================================
    # MONNAIES DES ANNONCES
    # =========================================================

    # La monnaie n'est PAS imposée par NexMarket.
    #
    # Le vendeur choisit la monnaie lors de la création
    # de son annonce.
    #
    # Exemple :
    #   prix = 50000
    #   currency = "XAF"
    #
    # La valeur enregistrée dans le Listing reste la source
    # de vérité pour cette annonce.
    SUPPORTED_CURRENCIES: str = "XAF,XOF,USD,EUR"

    # =========================================================
    # JESSIKAPAY
    # =========================================================

    JESSIKAPAY_API_URL: str = (
        "https://preferred-antonia-youtub-c1a62de8.koyeb.app"
    )

    JESSIKAPAY_API_KEY: str = ""
    JESSIKAPAY_API_SECRET: str = ""

    # URL HTTPS publique du webhook NexMarket.
    JESSIKAPAY_WEBHOOK_URL: str = ""

    # JP du compte JessiKaPay de règlement de NEXA.
    #
    # Cette valeur est strictement réservée au backend.
    NEXA_JP_NUMBER: str = ""

    # =========================================================
    # TELEGRAM SECURITY
    # =========================================================

    # Durée maximale d'acceptation des données Telegram
    # utilisées pour authentifier une Mini App.
    TELEGRAM_AUTH_MAX_AGE_SECONDS: int = 86400

    # =========================================================
    # ANTI-ABUS / RATE LIMITING
    # =========================================================

    DEPOSIT_RATE_LIMIT_PER_MINUTE: int = 5

    WITHDRAW_RATE_LIMIT_PER_MINUTE: int = 3

    JP_LOOKUP_RATE_LIMIT_PER_MINUTE: int = 10

    LISTING_CREATE_RATE_LIMIT_PER_MINUTE: int = 3

    # =========================================================
    # ESCROW
    # =========================================================

    # Délai de protection après le transfert du canal.
    # Cette valeur est configurable.
    ESCROW_PROTECTION_MINUTES: int = 60

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
    # HELPERS
    # =========================================================

    def get_cors_origins(self) -> list[str]:
        """
        Transforme une chaîne d'origines séparées par des virgules
        en liste utilisable par FastAPI.
        """

        if not self.CORS_ORIGINS.strip():
            return [self.FRONTEND_URL]

        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    def get_supported_currencies(self) -> list[str]:
        """
        Retourne les monnaies autorisées pour les annonces.
        """

        return [
            currency.strip().upper()
            for currency in self.SUPPORTED_CURRENCIES.split(",")
            if currency.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
