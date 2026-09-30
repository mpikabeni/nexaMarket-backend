from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    APP_NAME: str = "NexMarket API"; APP_VERSION: str = "1.0.0"; ENVIRONMENT: str = "production"
    FRONTEND_URL: str = "https://nexamarke.netlify.app"
    DATABASE_URL: str
    TELEGRAM_BOT_TOKEN: str; TELEGRAM_BOT_USERNAME: str = ""; TELEGRAM_WEBHOOK_SECRET: str = ""
    JWT_SECRET: str; JWT_ALGORITHM: str = "HS256"; JWT_EXPIRE_MINUTES: int = 10080
    ADMIN_CODE: str = ""
    NEXMARKET_FEE_RATE: float = 0.05
    SUPPORTED_CURRENCIES: str = "XAF,XOF,USD,EUR"
    JESSIKAPAY_API_URL: str = "https://preferred-antonia-youtub-c1a62de8.koyeb.app"
    JESSIKAPAY_API_KEY: str = ""; JESSIKAPAY_API_SECRET: str = ""; JESSIKAPAY_WEBHOOK_URL: str = ""; NEXA_JP_NUMBER: str = ""
    TELEGRAM_AUTH_MAX_AGE_SECONDS: int = 86400
    ESCROW_PROTECTION_MINUTES: int = 60
    CORS_ORIGINS: str = ""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore")
    @property
    def cors_origins_list(self):
        vals=[x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]
        if self.FRONTEND_URL and self.FRONTEND_URL.rstrip("/") not in vals: vals.append(self.FRONTEND_URL.rstrip("/"))
        return vals
    def get_supported_currencies(self): return [x.strip().upper() for x in self.SUPPORTED_CURRENCIES.split(",") if x.strip()]
@lru_cache
def get_settings(): return Settings()
settings=get_settings()
