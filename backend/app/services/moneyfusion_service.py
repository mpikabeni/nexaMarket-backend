import logging
from typing import Any, Optional

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class MoneyFusionError(Exception):
    """Erreur générale Money Fusion."""


class MoneyFusionConfigurationError(MoneyFusionError):
    """Configuration Money Fusion manquante."""


class MoneyFusionAPIError(MoneyFusionError):
    """Erreur retournée par l'API Money Fusion."""


class MoneyFusionService:
    """
    Service centralisé pour Money Fusion.

    Fonctions :
    - création d'un paiement Payin
    - vérification du statut d'un paiement
    - récupération des méthodes de retrait
    - création d'un retrait Payout
    """

    # =========================================================
    # OUTILS INTERNES
    # =========================================================

    @staticmethod
    def _require_payin_url() -> str:
        url = (settings.MONEYFUSION_API_URL or "").strip()

        if not url:
            raise MoneyFusionConfigurationError(
                "MONEYFUSION_API_URL n'est pas configurée."
            )

        return url

    @staticmethod
    def _require_payout_key() -> str:
        key = (settings.MONEYFUSION_API_KEY or "").strip()

        if not key:
            raise MoneyFusionConfigurationError(
                "MONEYFUSION_API_KEY n'est pas configurée."
            )

        return key

    @staticmethod
    def _clean_phone(phone: str) -> str:
        """
        Nettoie légèrement le numéro sans modifier
        sa structure métier.
        """
        if not phone:
            return ""

        return (
            str(phone)
            .strip()
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

    @staticmethod
    def _clean_name(name: Optional[str]) -> str:
        if not name:
            return "Client NexMarket"

        name = " ".join(str(name).strip().split())

        return name[:150] if name else "Client NexMarket"

    @staticmethod
    def _money_value(value: Any) -> float:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise MoneyFusionError(
                f"Montant invalide : {value}"
            )

        if amount <= 0:
            raise MoneyFusionError(
                "Le montant doit être supérieur à zéro."
            )

        return round(amount, 2)

    @staticmethod
    def _ensure_dict(data: Any) -> dict:
        if not isinstance(data, dict):
            raise MoneyFusionAPIError(
                "Réponse Money Fusion invalide."
            )

        return data

    # =========================================================
    # CREATION D'UN PAIEMENT
    # =========================================================

    async def create_payment(
        self,
        amount: float,
        article_name: str,
        customer_name: str,
        customer_phone: str,
        user_id: int,
        order_id: int,
        return_url: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> dict:
        """
        Crée une session de paiement Money Fusion.

        Retour attendu notamment :
        {
            "statut": true,
            "token": "...",
            "message": "...",
            "url": "..."
        }
        """

        api_url = self._require_payin_url()

        total_price = self._money_value(amount)

        phone = self._clean_phone(customer_phone)

        if not phone:
            raise MoneyFusionError(
                "Le numéro de téléphone du client est obligatoire."
            )

        name = self._clean_name(customer_name)

        article = str(article_name).strip() or "Transaction NexMarket"

        payload = {
            "totalPrice": total_price,
            "article": [
                {
                    article: total_price
                }
            ],
            "personal_Info": [
                {
                    "userId": user_id,
                    "orderId": order_id,
                }
            ],
            "numeroSend": phone,
            "nomclient": name,
            "return_url": (
                return_url
                or settings.MONEYFUSION_RETURN_URL
                or settings.FRONTEND_URL
            ),
            "webhook_url": (
                webhook_url
                or settings.MONEYFUSION_PAYIN_WEBHOOK_URL
                or None
            ),
        }

        # Supprime les valeurs None.
        payload = {
            key: value
            for key, value in payload.items()
            if value is not None
        }

        logger.info(
            "Création paiement Money Fusion pour order_id=%s",
            order_id,
        )

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            ) as client:

                response = await client.post(
                    api_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

        except httpx.TimeoutException as exc:
            logger.exception(
                "Timeout Money Fusion lors de la création du paiement."
            )
            raise MoneyFusionAPIError(
                "Money Fusion n'a pas répondu à temps."
            ) from exc

        except httpx.RequestError as exc:
            logger.exception(
                "Erreur réseau Money Fusion."
            )
            raise MoneyFusionAPIError(
                "Impossible de contacter Money Fusion."
            ) from exc

        if response.status_code >= 400:
            logger.error(
                "Money Fusion HTTP %s : %s",
                response.status_code,
                response.text[:1000],
            )

            raise MoneyFusionAPIError(
                f"Money Fusion a retourné HTTP "
                f"{response.status_code}."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise MoneyFusionAPIError(
                "Money Fusion a retourné une réponse non JSON."
            ) from exc

        data = self._ensure_dict(data)

        return data

    # =========================================================
    # STATUT D'UN PAIEMENT
    # =========================================================

    async def get_payment_status(
        self,
        token: str,
    ) -> dict:
        """
        Vérifie directement le statut d'un paiement.

        Endpoint officiel :
        /paiementNotif/{token}
        """

        token = str(token or "").strip()

        if not token:
            raise MoneyFusionError(
                "Token Money Fusion manquant."
            )

        base_url = (
            settings.MONEYFUSION_PAYMENT_STATUS_URL
            or "https://pay.moneyfusion.net/paiementNotif"
        ).rstrip("/")

        url = f"{base_url}/{token}"

        logger.info(
            "Vérification paiement Money Fusion token=%s",
            token,
        )

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
            ) as client:

                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                    },
                )

        except httpx.TimeoutException as exc:
            raise MoneyFusionAPIError(
                "Timeout lors de la vérification du paiement."
            ) from exc

        except httpx.RequestError as exc:
            raise MoneyFusionAPIError(
                "Impossible de vérifier le paiement Money Fusion."
            ) from exc

        if response.status_code >= 400:
            raise MoneyFusionAPIError(
                f"Money Fusion a retourné HTTP "
                f"{response.status_code}."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise MoneyFusionAPIError(
                "Réponse de statut Money Fusion non JSON."
            ) from exc

        return self._ensure_dict(data)

    # =========================================================
    # EXTRAIRE LE STATUT
    # =========================================================

    @staticmethod
    def extract_payment_status(
        data: dict,
    ) -> Optional[str]:
        """
        Retourne le statut présent dans une réponse Money Fusion.

        Valeurs connues :
        - pending
        - failure
        - no paid
        - paid
        """

        if not isinstance(data, dict):
            return None

        possible_keys = (
            "status",
            "statut",
            "payment_status",
            "paymentStatus",
            "state",
        )

        for key in possible_keys:
            value = data.get(key)

            if value is not None:
                return str(value).strip().lower()

        # Certaines réponses peuvent contenir les informations
        # dans une sous-structure.
        for key in (
            "data",
            "payment",
            "transaction",
        ):
            nested = data.get(key)

            if isinstance(nested, dict):
                for status_key in possible_keys:
                    value = nested.get(status_key)

                    if value is not None:
                        return str(value).strip().lower()

        return None

    # =========================================================
    # EXTRAIRE LE TOKEN
    # =========================================================

    @staticmethod
    def extract_payment_token(
        data: dict,
    ) -> Optional[str]:
        if not isinstance(data, dict):
            return None

        possible_keys = (
            "token",
            "tokenPay",
            "token_pay",
            "payment_token",
        )

        for key in possible_keys:
            value = data.get(key)

            if value:
                return str(value).strip()

        for key in (
            "data",
            "payment",
            "transaction",
        ):
            nested = data.get(key)

            if isinstance(nested, dict):
                for token_key in possible_keys:
                    value = nested.get(token_key)

                    if value:
                        return str(value).strip()

        return None

    # =========================================================
    # EXTRAIRE LE MONTANT
    # =========================================================

    @staticmethod
    def extract_payment_amount(
        data: dict,
    ) -> Optional[float]:
        if not isinstance(data, dict):
            return None

        possible_keys = (
            "Montant",
            "montant",
            "amount",
            "totalPrice",
            "total",
        )

        for key in possible_keys:
            value = data.get(key)

            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        for key in (
            "data",
            "payment",
            "transaction",
        ):
            nested = data.get(key)

            if isinstance(nested, dict):
                for amount_key in possible_keys:
                    value = nested.get(amount_key)

                    if value is not None:
                        try:
                            return float(value)
                        except (TypeError, ValueError):
                            pass

        return None

    # =========================================================
    # METHODES DE RETRAIT
    # =========================================================

    async def get_withdraw_methods(self) -> dict:
        """
        Récupère les méthodes de retrait disponibles
        chez Money Fusion.
        """

        url = (
            settings.MONEYFUSION_WITHDRAW_METHODS_URL
            or "https://pay.moneyfusion.net/api/v1/withdraw/methods"
        )

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
            ) as client:

                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                    },
                )

        except httpx.TimeoutException as exc:
            raise MoneyFusionAPIError(
                "Timeout lors de la récupération "
                "des méthodes de retrait."
            ) from exc

        except httpx.RequestError as exc:
            raise MoneyFusionAPIError(
                "Impossible de récupérer les méthodes "
                "de retrait Money Fusion."
            ) from exc

        if response.status_code >= 400:
            raise MoneyFusionAPIError(
                f"Money Fusion a retourné HTTP "
                f"{response.status_code}."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise MoneyFusionAPIError(
                "Réponse des méthodes de retrait non JSON."
            ) from exc

        return self._ensure_dict(data)

    # =========================================================
    # CREATION D'UN RETRAIT
    # =========================================================

    async def create_withdrawal(
        self,
        amount: float,
        country_code: str,
        phone: str,
        withdraw_mode: str,
        webhook_url: Optional[str] = None,
    ) -> dict:
        """
        Effectue une demande de retrait Money Fusion.

        IMPORTANT :
        Le solde NexMarket doit être vérifié et bloqué
        AVANT d'appeler cette fonction.
        """

        api_key = self._require_payout_key()

        url = (
            settings.MONEYFUSION_WITHDRAW_URL
            or "https://pay.moneyfusion.net/api/v1/withdraw"
        )

        total_amount = self._money_value(amount)

        country = str(country_code or "").strip().upper()

        if not country:
            raise MoneyFusionError(
                "Le code pays est obligatoire."
            )

        cleaned_phone = self._clean_phone(phone)

        if not cleaned_phone:
            raise MoneyFusionError(
                "Le numéro de retrait est obligatoire."
            )

        mode = str(withdraw_mode or "").strip()

        if not mode:
            raise MoneyFusionError(
                "Le mode de retrait est obligatoire."
            )

        payload = {
            "countryCode": country,
            "phone": cleaned_phone,
            "amount": total_amount,
            "withdraw_mode": mode,
            "webhook_url": (
                webhook_url
                or settings.MONEYFUSION_PAYOUT_WEBHOOK_URL
                or None
            ),
        }

        payload = {
            key: value
            for key, value in payload.items()
            if value is not None
        }

        logger.info(
            "Création retrait Money Fusion amount=%s country=%s",
            total_amount,
            country,
        )

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            ) as client:

                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "moneyfusion-private-key": api_key,
                    },
                )

        except httpx.TimeoutException as exc:
            raise MoneyFusionAPIError(
                "Money Fusion n'a pas répondu à temps "
                "pour le retrait."
            ) from exc

        except httpx.RequestError as exc:
            raise MoneyFusionAPIError(
                "Impossible de contacter Money Fusion "
                "pour le retrait."
            ) from exc

        if response.status_code >= 400:
            logger.error(
                "Money Fusion payout HTTP %s : %s",
                response.status_code,
                response.text[:1000],
            )

            raise MoneyFusionAPIError(
                f"Money Fusion a retourné HTTP "
                f"{response.status_code}."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise MoneyFusionAPIError(
                "Réponse du retrait Money Fusion non JSON."
            ) from exc

        return self._ensure_dict(data)


# =============================================================
# INSTANCE UNIQUE
# =============================================================

moneyfusion_service = MoneyFusionService()