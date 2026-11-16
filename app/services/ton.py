"""Outils TON / GRAM : adresses, montants et lecture de la blockchain.

Le serveur ne possède AUCUNE clé privée : il lit seulement la blockchain pour
constater qu'un paiement est arrivé. L'envoi des GRAM aux vendeurs (et les
remboursements) est fait à la main par l'administrateur depuis son portefeuille.
"""

from __future__ import annotations

import base64
import binascii
import logging
from decimal import Decimal

logger = logging.getLogger("nexmarket.ton")

NANO = Decimal(1_000_000_000)  # 1 GRAM = 10^9 nanoGRAM


# ------------------------------------------------------------ adresses
def _crc16(data: bytes) -> int:
    """CRC16-CCITT (XMODEM) utilisé par les adresses TON « user-friendly »."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_address(value: str) -> tuple[int, bytes] | None:
    """Renvoie (workchain, hash 32 octets) ou None si l'adresse est invalide.

    Accepte la forme « user-friendly » (48 caractères base64, somme de contrôle
    vérifiée) et la forme brute « 0:abcdef… ». Deux écritures d'une même
    adresse donnent le même résultat : on peut donc les comparer.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()

    if ":" in text:  # forme brute  workchain:hex
        wc, _, hexpart = text.partition(":")
        try:
            workchain = int(wc)
            raw = bytes.fromhex(hexpart)
        except ValueError:
            return None
        return (workchain, raw) if len(raw) == 32 and workchain in (0, -1) else None

    if len(text) != 48:
        return None
    try:
        data = base64.urlsafe_b64decode(text.replace("+", "-").replace("/", "_"))
    except (binascii.Error, ValueError):
        return None
    if len(data) != 36:
        return None
    if _crc16(data[:34]) != int.from_bytes(data[34:], "big"):
        return None  # faute de frappe : somme de contrôle fausse
    if data[0] not in (0x11, 0x51):  # mainnet : rebondissable (0x11) ou non (0x51)
        return None
    workchain = data[1] - 256 if data[1] > 127 else data[1]
    return (workchain, bytes(data[2:34])) if workchain in (0, -1) else None


def is_valid_address(value: str) -> bool:
    return parse_address(value) is not None


def same_address(a: str | None, b: str | None) -> bool:
    pa, pb = parse_address(a or ""), parse_address(b or "")
    return pa is not None and pa == pb


# ------------------------------------------------------------ montants
def to_nano(amount) -> int:
    return int((Decimal(str(amount)) * NANO).to_integral_value())


def from_nano(value) -> Decimal:
    return Decimal(str(value)) / NANO


def payment_link(address: str, amount, comment: str) -> str:
    """Lien de paiement standard TON (ouvre un portefeuille compatible)."""
    from urllib.parse import quote
    return f"ton://transfer/{address}?amount={to_nano(amount)}&text={quote(comment)}"


# ------------------------------------------------------------ blockchain
def _body_contains(msg: dict, needle: str) -> bool:
    """Le commentaire du paiement se trouve-t-il dans le message ?"""
    content = (msg or {}).get("message_content") or {}
    decoded = content.get("decoded") or {}
    comment = decoded.get("comment") or decoded.get("text")
    if isinstance(comment, str) and comment.strip() == needle:
        return True
    body = content.get("body") or (msg or {}).get("body")
    if isinstance(body, str):
        try:
            raw = base64.b64decode(body + "=" * (-len(body) % 4))
            return needle.encode() in raw
        except (binascii.Error, ValueError):
            return False
    return False


def _ok(tx: dict) -> bool:
    """La transaction a-t-elle réussi (pas de rebond / d'échec) ?"""
    desc = tx.get("description") or {}
    if desc.get("aborted") is True:
        return False
    compute = desc.get("compute_ph") or {}
    if compute.get("success") is False:
        return False
    action = desc.get("action") or {}
    if action.get("success") is False:
        return False
    return True


async def fetch_transactions(address: str, *, limit: int = 100) -> list[dict]:
    """Dernières transactions du compte (les plus récentes d'abord)."""

    import httpx

    from app.config import settings

    headers = {"X-API-Key": settings.TON_API_KEY} if settings.TON_API_KEY else {}
    params = {"account": address, "limit": limit, "sort": "desc"}
    async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
        response = await client.get(f"{settings.TON_API_BASE.rstrip('/')}/transactions", params=params)
        response.raise_for_status()
        data = response.json()
    txs = data.get("transactions") if isinstance(data, dict) else None
    return txs if isinstance(txs, list) else []


def find_incoming_payment(
    transactions: list[dict],
    *,
    my_address: str,
    comment: str,
    min_amount,
) -> dict | None:
    """Cherche un paiement ENTRANT : bon commentaire, montant suffisant, réussi.

    Renvoie {"hash", "amount", "source"} ou None. Jamais de faux positif : le
    commentaire exact (unique par transaction) ET le montant sont exigés.
    """

    need = to_nano(min_amount)
    for tx in transactions:
        msg = tx.get("in_msg") or {}
        if not msg.get("source"):          # message externe : pas un virement
            continue
        dest = msg.get("destination")
        if dest and not same_address(dest, my_address):
            continue
        try:
            value = int(msg.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if value < need or not _ok(tx):
            continue
        if not _body_contains(msg, comment):
            continue
        return {"hash": tx.get("hash"), "amount": from_nano(value), "source": msg.get("source")}
    return None


def find_outgoing_payment(
    transactions: list[dict],
    *,
    to_address: str,
    min_amount,
    tx_hash: str | None = None,
) -> dict | None:
    """Cherche un envoi SORTANT vers `to_address` d'au moins `min_amount`."""

    need = to_nano(min_amount)
    for tx in transactions:
        if tx_hash and tx.get("hash") != tx_hash:
            continue
        if not _ok(tx):
            continue
        for out in tx.get("out_msgs") or []:
            if not same_address(out.get("destination"), to_address):
                continue
            try:
                value = int(out.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if value >= need:
                return {"hash": tx.get("hash"), "amount": from_nano(value)}
    return None
