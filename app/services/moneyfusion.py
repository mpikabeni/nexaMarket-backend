"""
Client MoneyFusion (remplace JessiKaPay).

Doc officielle : https://docs.moneyfusion.net

- Dépôt (payin)  : POST sur le lien d'API de votre application -> `token` + `url`
  de la page de paiement ; statut : GET /paiementNotif/{token}.
- Retrait (payout) : POST /api/v1/withdraw (en-tête moneyfusion-private-key) ->
  `tokenPay` ; statut : GET /api/v1/payout/check-status/{token}. Le payout est
  ASYNCHRONE : la réponse initiale veut seulement dire « demande acceptée ».
- Catalogue : GET /api/v1/withdraw/methods = pays, devise et réseaux (opérateurs)
  réellement disponibles. C'est la source de vérité : aucun pays ni réseau n'est
  codé en dur, sauf une liste de secours si MoneyFusion est injoignable.

Les webhooks MoneyFusion ne sont pas signés (voir routes/webhooks.py) : on ne s'y
fie jamais, on relit toujours le statut auprès de l'API.
"""

from __future__ import annotations

import json
import logging
import time
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from urllib.parse import quote

import httpx

from app.config import settings
from app.services.countries import country_dial, country_name

logger = logging.getLogger("nexmarket.moneyfusion")

CFA_CURRENCIES = {"XOF", "XAF"}  # parité fixe 1 XOF = 1 XAF

# Liste de secours (doc MoneyFusion) : utilisée SEULEMENT si l'API des méthodes
# est injoignable et qu'aucune liste récente n'est en mémoire. MoneyFusion
# valide de toute façon le pays/réseau à chaque retrait.
FALLBACK_METHODS: list[dict] = [
    {"code": "ci", "country": "Côte d'Ivoire", "currency": "XOF", "paymentMethods": [
        {"key": "orange-money-ci", "name": "Orange"}, {"key": "mtn-ci", "name": "MTN"},
        {"key": "moov-ci", "name": "Moov"}, {"key": "wave-ci", "name": "Wave"}]},
    {"code": "sn", "country": "Sénégal", "currency": "XOF", "paymentMethods": [
        {"key": "orange-money-senegal", "name": "Orange"}, {"key": "free-money-senegal", "name": "Free"},
        {"key": "wave-senegal", "name": "Wave"}, {"key": "expresso-senegal", "name": "Expresso"}]},
    {"code": "bf", "country": "Burkina Faso", "currency": "XOF", "paymentMethods": [
        {"key": "orange-money-burkina", "name": "Orange"}, {"key": "moov-burkina-faso", "name": "Moov"}]},
    {"code": "bj", "country": "Bénin", "currency": "XOF", "paymentMethods": [
        {"key": "mtn-benin", "name": "MTN"}, {"key": "moov-benin", "name": "Moov"}]},
    {"code": "tg", "country": "Togo", "currency": "XOF", "paymentMethods": [
        {"key": "t-money-togo", "name": "T-Money"}, {"key": "moov-togo", "name": "Moov"}]},
    {"code": "ml", "country": "Mali", "currency": "XOF", "paymentMethods": [
        {"key": "orange-money-mali", "name": "Orange"}]},
    {"code": "cg", "country": "Congo Brazzaville", "currency": "XAF", "paymentMethods": [
        {"key": "mtn-cg", "name": "MTN"}]},
    {"code": "cm", "country": "Cameroun", "currency": "XAF", "paymentMethods": [
        {"key": "orange-money-cm", "name": "Orange"}, {"key": "mtn-cm", "name": "MTN"}]},
    {"code": "ga", "country": "Gabon", "currency": "XAF", "paymentMethods": [
        {"key": "airtel-money-ga", "name": "Airtel"}, {"key": "libertis-ga", "name": "Libertis"}]},
    {"code": "cd", "country": "Congo RDC", "currency": "CDF", "paymentMethods": [
        {"key": "airtel-money-cd", "name": "Airtel"}]},
]

METHODS_TTL_SECONDS = 3600


class MoneyFusionError(Exception):
    """
    Erreur liée à l'API MoneyFusion.

    ambiguous=True : l'issue est INCONNUE (timeout, erreur réseau, réponse 5xx,
    réponse incomplète) : MoneyFusion a peut-être quand même traité la demande.
    Il ne faut alors JAMAIS rendre l'argent automatiquement (risque de double
    paiement) : un admin vérifie dans le tableau de bord MoneyFusion.
    """

    def __init__(self, message: str = "", *, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


# ============================================================
# OUTILS PURS (testables sans réseau)
# ============================================================

def _num(value) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def map_payin_status(raw) -> str:
    """paid -> paid ; failure -> failed ; pending / no paid -> pending.

    « no paid » (paiement non terminé) reste volontairement NON final : un
    utilisateur peut encore payer, et la tâche de fond arrête de toute façon
    de vérifier après 48 h.
    """

    value = str(raw or "").strip().lower()

    if value == "paid":
        return "paid"

    if value in {"failure", "failed", "cancelled", "canceled"}:
        return "failed"

    if value in {"pending", "no paid", "no_paid", "nopaid", ""}:
        return "pending"

    logger.warning("Statut de dépôt MoneyFusion non reconnu : %r", raw)
    return "pending"


def map_payout_status(raw) -> str:
    """success -> completed ; failed -> failed ; le reste -> pending (jamais final)."""

    value = str(raw or "").strip().lower()

    if value in {"success", "completed", "paid"}:
        return "completed"

    if value in {"failed", "failure", "cancelled", "canceled"}:
        return "failed"

    if value not in {"pending", "processing", ""}:
        logger.warning("Statut de retrait MoneyFusion non reconnu : %r", raw)

    return "pending"


def fx_rates() -> dict[str, Decimal]:
    """Taux {DEVISE: valeur d'une unité en XAF} lus dans MONEYFUSION_FX_TO_XAF."""

    raw = (settings.MONEYFUSION_FX_TO_XAF or "").strip()

    if not raw:
        return {}

    try:
        data = json.loads(raw)
        rates = {
            str(k).upper(): Decimal(str(v))
            for k, v in data.items()
            if Decimal(str(v)) > 0
        }
        return rates
    except (ValueError, InvalidOperation, AttributeError, TypeError):
        logger.error("MONEYFUSION_FX_TO_XAF invalide (JSON attendu) : ignoré.")
        return {}


def rate_to_xaf(currency: str) -> Decimal | None:
    code = (currency or "").upper()

    if code in CFA_CURRENCIES:
        return Decimal(1)

    return fx_rates().get(code)


def to_local_amount(amount_xaf, currency: str) -> int | None:
    """Montant XAF -> montant dans la devise locale du pays (arrondi vers le bas).

    None si la devise n'est pas gérée (aucun taux configuré) : on ne convertit
    jamais avec un taux inventé.
    """

    rate = rate_to_xaf(currency)

    if rate is None:
        return None

    return int((Decimal(str(amount_xaf)) / rate).to_integral_value(rounding=ROUND_FLOOR))


def normalize_methods(data) -> list[dict]:
    """Réponse de /withdraw/methods -> [{code, name, currency, methods:[{key,name}]}]."""

    items = data.get("data") if isinstance(data, dict) else data

    if not isinstance(items, list):
        return []

    result: list[dict] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or "").strip().lower()

        if not code:
            continue

        methods = []

        for method in item.get("paymentMethods") or []:
            if isinstance(method, dict):
                key = str(method.get("key") or "").strip()
                name = str(method.get("name") or key).strip()
            else:
                key = str(method).strip()
                name = key

            if key:
                methods.append({"key": key, "name": name})

        if not methods:
            continue

        result.append(
            {
                "code": code,
                "name": str(item.get("country") or country_name(code) or code.upper()),
                "currency": str(item.get("currency") or "").upper(),
                "methods": methods,
            }
        )

    return result


def public_catalog(countries: list[dict]) -> list[dict]:
    """Pays utilisables : ceux dont la devise est convertible en XAF (CFA ou taux configuré)."""

    visible = []

    for country in countries:
        if rate_to_xaf(country["currency"]) is None:
            continue

        dial = country_dial(country["code"])

        visible.append(
            {
                "code": country["code"].upper(),
                "name": country["name"],
                "currency": country["currency"],
                "dial": f"+{dial}" if dial else "",
                "methods": country["methods"],
            }
        )

    return sorted(visible, key=lambda c: c["name"])


def find_method(countries: list[dict], code: str, method_key: str) -> dict | None:
    """Le (pays, réseau) existe-t-il ET est-il utilisable ? Retourne le pays, sinon None."""

    code = (code or "").strip().lower()

    for country in countries:
        if country["code"].lower() != code:
            continue

        if rate_to_xaf(country["currency"]) is None:
            return None

        if any(m["key"] == method_key for m in country["methods"]):
            return country

    return None


def extract_reference(personal_info) -> str | None:
    """Notre référence, renvoyée par MoneyFusion dans personal_Info."""

    if isinstance(personal_info, list):
        for item in personal_info:
            if isinstance(item, dict) and item.get("reference"):
                return str(item["reference"])

    return None


# ============================================================
# CLIENT HTTP
# ============================================================

class MoneyFusionService:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._methods_cache: dict = {"at": 0.0, "countries": None}

    @property
    def base_url(self) -> str:
        return (settings.MONEYFUSION_BASE_URL or "https://pay.moneyfusion.net").rstrip("/")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=6.0, read=20.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            )

        return self._client

    def _private_headers(self) -> dict[str, str]:
        key = (settings.MONEYFUSION_PRIVATE_KEY or "").strip()

        if not key:
            raise MoneyFusionError("MoneyFusion n'est pas configuré (MONEYFUSION_PRIVATE_KEY).")

        return {"moneyfusion-private-key": key}

    async def _request(self, method: str, url: str, *, payload: dict | None = None,
                       headers: dict | None = None):
        request_headers = {"Content-Type": "application/json", **(headers or {})}

        try:
            response = await self._get_client().request(
                method,
                url,
                json=payload,
                headers=request_headers,
            )

        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # La connexion n'a pas abouti : la requête n'est JAMAIS partie.
            raise MoneyFusionError(
                "MoneyFusion est injoignable pour le moment. Réessayez dans un instant.",
                ambiguous=False,
            ) from exc

        except httpx.RequestError as exc:
            raise MoneyFusionError(
                f"Impossible de contacter MoneyFusion : {type(exc).__name__}",
                ambiguous=True,
            ) from exc

        if response.status_code >= 400:
            detail = response.text[:300]

            try:
                body = response.json()
                if isinstance(body, dict) and body.get("message"):
                    detail = str(body["message"])[:300]
            except ValueError:
                pass

            raise MoneyFusionError(
                f"MoneyFusion HTTP {response.status_code} : {detail}",
                ambiguous=response.status_code >= 500,
            )

        try:
            return response.json()

        except ValueError as exc:
            raise MoneyFusionError(
                "MoneyFusion a retourné une réponse JSON invalide.",
                ambiguous=True,
            ) from exc

    # ========================================================
    # DÉPÔT (payin)
    # ========================================================

    async def create_payment(
        self,
        *,
        amount: int,
        phone: str,
        name: str,
        reference: str,
        user_id: int,
        return_url: str = "",
        webhook_url: str = "",
    ) -> dict:
        """Crée la page de paiement. Retourne {"token", "url"}."""

        api_url = (settings.MONEYFUSION_API_URL or "").strip()

        if not api_url:
            raise MoneyFusionError("MoneyFusion n'est pas configuré (MONEYFUSION_API_URL).")

        body: dict = {
            "totalPrice": int(amount),
            "article": [{"Dépôt NexMarket": int(amount)}],
            "numeroSend": phone,
            "nomclient": (name or "NexMarket")[:60],
            # Notre référence revient dans le statut et les webhooks.
            "personal_Info": [{"reference": reference, "user_id": user_id}],
        }

        if return_url:
            body["return_url"] = return_url

        if webhook_url:
            body["webhook_url"] = webhook_url

        data = await self._request("POST", api_url, payload=body)

        if (
            not isinstance(data, dict)
            or data.get("statut") is not True
            or not data.get("token")
            or not data.get("url")
        ):
            message = data.get("message") if isinstance(data, dict) else None
            raise MoneyFusionError(
                str(message or "MoneyFusion n'a pas créé la page de paiement."),
                ambiguous=False,
            )

        return {"token": str(data["token"]), "url": str(data["url"])}

    async def get_payment_status(self, token: str) -> dict:
        """Statut normalisé d'un dépôt.

        {"status": paid|pending|failed|unknown, "amount": Montant NET reçu,
         "fees": frais, "method": moyen, "reference": notre référence}
        """

        data = await self._request(
            "GET", f"{self.base_url}/paiementNotif/{quote(str(token), safe='')}"
        )

        if not isinstance(data, dict) or data.get("statut") is not True:
            return {"status": "unknown", "amount": None, "fees": None, "method": None, "reference": None}

        info = data.get("data") or {}

        return {
            "status": map_payin_status(info.get("statut")),
            "raw_status": str(info.get("statut") or ""),
            "amount": _num(info.get("Montant")),
            "fees": _num(info.get("frais")),
            "method": info.get("moyen"),
            "reference": extract_reference(info.get("personal_Info")),
        }

    # ========================================================
    # RETRAIT (payout)
    # ========================================================

    async def withdraw(
        self,
        *,
        country: str,
        method: str,
        phone: str,
        amount: int,
        webhook_url: str = "",
    ) -> dict:
        """Demande un retrait. Retourne {"token"} (tokenPay).

        Refus explicite (statut false, 4xx) -> MoneyFusionError(ambiguous=False).
        Accepté sans jeton, timeout ou 5xx -> ambiguous=True.
        """

        body: dict = {
            "countryCode": country.lower(),
            "phone": phone,
            "amount": int(amount),
            "withdraw_mode": method,
        }

        if webhook_url:
            body["webhook_url"] = webhook_url

        data = await self._request(
            "POST",
            f"{self.base_url}/api/v1/withdraw",
            payload=body,
            headers=self._private_headers(),
        )

        if not isinstance(data, dict):
            raise MoneyFusionError("Réponse MoneyFusion invalide.", ambiguous=True)

        if data.get("statut") is True:
            token = data.get("tokenPay")

            if not token:
                raise MoneyFusionError(
                    "MoneyFusion a accepté le retrait sans jeton de suivi.",
                    ambiguous=True,
                )

            return {"token": str(token), "message": data.get("message")}

        raise MoneyFusionError(
            str(data.get("message") or "Retrait refusé par MoneyFusion."),
            ambiguous=False,
        )

    async def get_payout_status(self, token: str) -> dict:
        """{"status": completed|failed|pending|unknown}."""

        data = await self._request(
            "GET",
            f"{self.base_url}/api/v1/payout/check-status/{quote(str(token), safe='')}",
            headers=self._private_headers(),
        )

        if not isinstance(data, dict) or data.get("success") is not True:
            return {"status": "unknown"}

        info = data.get("data") or {}

        return {"status": map_payout_status(info.get("status")), "raw_status": str(info.get("status") or "")}

    # ========================================================
    # CATALOGUE PAYS / RÉSEAUX
    # ========================================================

    async def get_countries(self, *, force: bool = False) -> tuple[list[dict], str]:
        """(pays, source) avec source = live | cache | fallback. Mis en cache 1 h."""

        cache = self._methods_cache
        fresh = cache["countries"] is not None and (time.time() - cache["at"]) < METHODS_TTL_SECONDS

        if fresh and not force:
            return cache["countries"], "cache"

        try:
            headers = {}
            if (settings.MONEYFUSION_PRIVATE_KEY or "").strip():
                headers = self._private_headers()

            data = await self._request(
                "GET", f"{self.base_url}/api/v1/withdraw/methods", headers=headers
            )
            countries = normalize_methods(data)

            if countries:
                cache["countries"] = countries
                cache["at"] = time.time()
                return countries, "live"

            logger.warning("MoneyFusion : liste des méthodes vide ou inattendue.")

        except MoneyFusionError as exc:
            logger.warning("MoneyFusion : liste des méthodes indisponible : %s", exc)

        if cache["countries"] is not None:
            return cache["countries"], "cache"  # liste périmée mais réelle

        return normalize_methods(FALLBACK_METHODS), "fallback"


moneyfusion_service = MoneyFusionService()
