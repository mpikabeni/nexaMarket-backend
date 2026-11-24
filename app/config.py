from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "NexMarket"
    APP_VERSION: str = "1.0.11"
    ENVIRONMENT: str = "production"

    FRONTEND_URL: str = "https://nexamarke.netlify.app"

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
    # FRAIS MONEYFUSION SUR LES DÉPÔTS
    # MoneyFusion prélève ses frais sur le paiement : le wallet est crédité
    # du montant NET confirmé par MoneyFusion (champ « Montant » du statut),
    # jamais plus que ce que NexMarket reçoit. Ce taux n'est qu'une
    # ESTIMATION affichée avant le paiement (voir la table de frais du
    # tableau de bord MoneyFusion, page « Fees »).
    # ========================================================

    MONEYFUSION_DEPOSIT_FEE_RATE: float = 0.05

    # JESSIKAPAY (prestataire actuel : paiement direct des achats + versement vendeur)
    JESSIKAPAY_BASE_URL: str = "https://preferred-antonia-youtub-c1a62de8.koyeb.app"
    JESSIKAPAY_API_KEY: str = ""
    JESSIKAPAY_API_SECRET: str = ""
    # Commission JessiKaPay prélevée sur ce que NexMarket reçoit (doc : 6 %).
    JESSIKAPAY_COMMISSION_RATE: float = 0.06
    # Numéro JP de NexMarket : reçoit les commissions (payout gratuit).
    NEXA_JP_NUMBER: str = ""

    # Comptes créés AVANT cette date (ISO) = comptes existants : ils gardent
    # leur NEXA ID dans le bot sans repasser par la création de compte.
    # Mets ici la date de mise en ligne de cette version.
    LEGACY_ACCOUNTS_BEFORE: str = "2026-11-25T00:00:00+00:00"

    # ========================================================
    # PAIEMENT EN GRAM (TON) : adresse de NexMarket + lecture blockchain
    # GRAM_RECEIVE_ADDRESS : adresse du portefeuille de NexMarket (copiée
    # depuis l'app Telegram « Argent »). Vide = paiement GRAM désactivé.
    # ========================================================

    # ========================================================
    # ASSISTANT IA des transactions : 2 fournisseurs GRATUITS en cascade.
    # L'assistant essaie d'abord le 1er de ASSISTANT_PROVIDERS qui a une clé ;
    # s'il est en panne ou limité (429), il passe automatiquement au suivant.
    # Aucune clé = assistant désactivé. Une seule clé suffit.
    #   Groq    : https://console.groq.com/keys
    #   Gemini  : https://aistudio.google.com/apikey
    # ========================================================

    # Prévenir TOUS les membres du bot quand une nouvelle annonce est publiée
    # (première publication seulement). Mettre à false pour couper.
    NOTIFY_NEW_LISTINGS: bool = True

    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    ASSISTANT_PROVIDERS: str = "groq,gemini"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_MODEL: str = "gemini-2.5-flash"

    GRAM_RECEIVE_ADDRESS: str = ""
    TON_API_BASE: str = "https://toncenter.com/api/v3"
    TON_API_KEY: str = ""

    # ========================================================
    # MONEYFUSION (dépôts + retraits Mobile Money, tous pays/réseaux)
    # Doc : https://docs.moneyfusion.net
    # ========================================================

    # Lien d'API des dépôts (tableau de bord > « API de paiement » > votre
    # application). Il contient votre clé : gardez-le secret.
    MONEYFUSION_API_URL: str = ""

    # Clé privée des retraits (tableau de bord > Paramètres). Envoyée dans
    # l'en-tête moneyfusion-private-key. L'IP sortante du serveur doit être
    # enregistrée chez MoneyFusion (IP fixe obligatoire).
    MONEYFUSION_PRIVATE_KEY: str = ""

    MONEYFUSION_BASE_URL: str = "https://pay.moneyfusion.net"

    # Segment secret de l'URL du webhook : /webhooks/moneyfusion/<secret>.
    # Vide = webhook désactivé (la vérification périodique suffit). Les
    # webhooks MoneyFusion ne sont pas signés : le serveur ne s'y fie jamais,
    # il relit toujours le statut auprès de l'API avant d'agir.
    MONEYFUSION_WEBHOOK_SECRET: str = ""

    # Pays à devise NON CFA (CDF, GNF, GHS...) : valeur d'UNE unité de la
    # devise locale en XAF, au format JSON, ex. {"GNF": 0.07, "CDF": 0.21}.
    # Sans taux, ces pays sont masqués dans les retraits (aucune conversion
    # inventée). XOF et XAF sont à parité 1:1 : aucun réglage nécessaire.
    MONEYFUSION_FX_TO_XAF: str = ""

    # Compte qui reçoit les commissions NexMarket (Mobile Money). Les trois
    # champs sont nécessaires ; sinon aucune commission n'est versée.
    NEXA_PAYOUT_COUNTRY: str = ""   # ex. cg
    NEXA_PAYOUT_METHOD: str = ""    # ex. mtn-cg
    NEXA_PAYOUT_PHONE: str = ""

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

    @field_validator("NEXMARKET_FEE_RATE")
    @classmethod
    def _fee_rate_is_fixed(cls, value: float) -> float:
        """La commission NexMarket est FIXE : 5 % du prix de vente.

        Même si NEXMARKET_FEE_RATE est modifiée sur Render, 5 % est appliqué.
        """

        return 0.05

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
