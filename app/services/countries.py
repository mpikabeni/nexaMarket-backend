"""
Pays pris en charge pour les dépôts JessiKaPay.

JessiKaPay EXIGE le champ `country` pour créer une demande de dépôt
(sinon HTTP 422 « body.country : Field required »). La liste correspond
à celle de l'application JessiKaPay ; les codes sont des codes ISO 3166-1
alpha-2, comme l'ancien code de NexMarket.
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

_BY_CODE = {code: (name, dial) for code, name, dial in COUNTRIES}


def country_dial(code: str) -> str | None:
    entry = _BY_CODE.get((code or "").upper())
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
