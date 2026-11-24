"""
Pays et indicatifs téléphoniques.

La liste des pays/réseaux DISPONIBLES pour retirer vient de MoneyFusion
(voir app/services/moneyfusion.py) ; cette table sert à connaître le nom
et l'indicatif d'un pays (pour nettoyer un numéro saisi avec « + » ou
« 00 ») et de liste de secours pour les dépôts. Codes ISO 3166-1 alpha-2.
"""

from __future__ import annotations

import re

# (code ISO, nom affiché, indicatif téléphonique)
COUNTRIES: list[tuple[str, str, str]] = [
    ("CI", "Côte d'Ivoire", "225"),
    ("SN", "Sénégal", "221"),
    ("TG", "Togo", "228"),
    ("BJ", "Bénin", "229"),
    ("BF", "Burkina Faso", "226"),
    ("ML", "Mali", "223"),
    ("CM", "Cameroun", "237"),
    ("GA", "Gabon", "241"),
    ("NE", "Niger", "227"),
    ("CG", "Congo Brazzaville", "242"),
    ("CD", "Congo RDC", "243"),
    ("GN", "Guinée-Conakry", "224"),
    ("TD", "Tchad", "235"),
    ("GH", "Ghana", "233"),
    ("KE", "Kenya", "254"),
    ("CF", "Centrafrique", "236"),
    ("GW", "Guinée-Bissau", "245"),
]

# Pays supplémentaires que MoneyFusion peut proposer (indicatif seulement :
# un pays n'est utilisable que s'il figure dans la liste de MoneyFusion).
_EXTRA: dict[str, tuple[str, str]] = {
    "RW": ("Rwanda", "250"),
    "NG": ("Nigeria", "234"),
    "UG": ("Ouganda", "256"),
    "TZ": ("Tanzanie", "255"),
    "ZM": ("Zambie", "260"),
    "SL": ("Sierra Leone", "232"),
    "LR": ("Libéria", "231"),
    "MR": ("Mauritanie", "222"),
    "BI": ("Burundi", "257"),
    "MG": ("Madagascar", "261"),
    "GM": ("Gambie", "220"),
}

_BY_CODE = {code: (name, dial) for code, name, dial in COUNTRIES}
_ALL = {**_EXTRA, **_BY_CODE}


def country_name(code: str) -> str | None:
    entry = _ALL.get((code or "").upper())
    return entry[0] if entry else None


def country_dial(code: str) -> str | None:
    entry = _ALL.get((code or "").upper())
    return entry[1] if entry else None


def is_supported(code: str) -> bool:
    return (code or "").upper() in _BY_CODE


def local_phone(code: str, raw: str) -> str:
    """
    Numéro LOCAL (chiffres uniquement), comme l'attendait l'ancien code :
    « +242 06 70 42 265 », « 00242067042265 » ou « 067042265 » donnent
    tous « 067042265 ». L'indicatif n'est retiré que si l'utilisateur l'a
    saisi avec « + » ou « 00 » (jamais deviné).
    """

    value = (raw or "").strip()
    international = value.startswith("+") or value.startswith("00")

    digits = re.sub(r"\D", "", value)

    if value.startswith("00"):
        digits = digits[2:]

    dial = country_dial(code)

    if international and dial and digits.startswith(dial):
        digits = digits[len(dial):]

    return digits
