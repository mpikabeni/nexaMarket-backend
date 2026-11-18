"""Assistant IA des transactions (Mistral) : orchestration.

Quand une transaction démarre (fonds bloqués), l'assistant prend la parole dans
la discussion acheteur / vendeur / admin, guide chacun pour le transfert du canal
et répond à leurs questions. Il est SUPERVISÉ : un administrateur lit la
discussion, peut écrire à tout moment, et c'est lui seul qui autorise le
transfert (bouton « Autoriser le transfert » ou console). L'assistant ne peut ni
toucher à l'argent, ni changer le statut : il écrit et il alerte.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.listing import Listing
from app.models.message import Message
from app.models.transaction import Transaction
from app.models.user import User
from app.services import assistant_logic as logic
from app.services.chat_service import (
    ROLE_LABELS,
    _admin_targets,
    chat_markup,
    display_name,
    post_assistant_message,
)
from app.services.notification_service import notify_telegram

logger = logging.getLogger("nexmarket.assistant")

ACTIVE_STATUSES = ("waiting_admin", "transfer_started", "protection_period", "disputed")
MAX_REPLIES_PER_TRANSACTION = 60
API_URL = "https://api.mistral.ai/v1/chat/completions"

_tasks: set[asyncio.Task] = set()
_locks: dict[int, asyncio.Lock] = {}
_last_alert: dict[int, tuple[str, float]] = {}


def enabled() -> bool:
    return bool((settings.MISTRAL_API_KEY or "").strip())


def _schedule(coro) -> None:
    if not enabled():
        coro.close()
        return
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def on_chat_opened(transaction_id: int) -> None:
    _schedule(_converse(
        transaction_id,
        "La discussion vient de s'ouvrir : les fonds sont bloqués. Présente-toi en une phrase "
        "(assistant IA supervisé par un administrateur), puis explique la suite à l'acheteur et au vendeur.",
        None,
    ))


def on_user_message(transaction_id: int, message_id: int) -> None:
    _schedule(_converse(
        transaction_id,
        "Un participant vient d'écrire (c'est le dernier message de l'historique).",
        message_id,
    ))


def on_status(transaction_id: int, status: str) -> None:
    _schedule(_converse(
        transaction_id,
        f"Le statut vient de passer à « {status} ». Informe les participants de la suite.",
        None,
    ))


async def _call_llm(system: str, user_prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {settings.MISTRAL_API_KEY.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "model": settings.ASSISTANT_MODEL,
        "max_tokens": 700,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
    }
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=45.0) as client:
        for attempt in range(2):
            try:
                response = await client.post(API_URL, json=body, headers=headers)
                if response.status_code in (429, 500, 502, 503, 529) and attempt == 0:
                    # L'offre gratuite Mistral limite le débit : on attend un peu avant de réessayer.
                    await asyncio.sleep(3)
                    continue
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, list):  # certains modèles renvoient des blocs
                    content = "".join(
                        block.get("text", "") for block in content if isinstance(block, dict)
                    )
                return content or ""
            except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(3)
    raise RuntimeError(f"Appel à l'assistant impossible : {last_error}")


async def _converse(transaction_id: int, trigger: str, trigger_message_id: int | None) -> None:
    lock = _locks.setdefault(transaction_id, asyncio.Lock())
    async with lock:
        try:
            # Plusieurs messages d'affilée : on attend un peu et seul le dernier déclenche.
            if trigger_message_id:
                await asyncio.sleep(3)

            async with AsyncSessionLocal() as db:
                transaction = await db.get(Transaction, transaction_id)
                if transaction is None or transaction.status not in ACTIVE_STATUSES:
                    return

                rows = (
                    await db.execute(
                        select(Message)
                        .where(Message.transaction_id == transaction_id)
                        .order_by(Message.id.desc())
                        .limit(30)
                    )
                ).scalars().all()
                rows.reverse()

                if trigger_message_id and (not rows or rows[-1].id != trigger_message_id):
                    return  # un message plus récent déclenchera la réponse

                sent = (
                    await db.scalar(
                        select(func.count()).select_from(Message).where(
                            Message.transaction_id == transaction_id,
                            Message.sender_role == "assistant",
                        )
                    )
                ) or 0
                if sent >= MAX_REPLIES_PER_TRANSACTION:
                    return

                users = {
                    u.id: u
                    for u in (
                        await db.execute(
                            select(User).where(
                                User.id.in_(
                                    {transaction.buyer_id, transaction.seller_id,
                                     *( [transaction.assigned_admin_id] if transaction.assigned_admin_id else [] )}
                                )
                            )
                        )
                    ).scalars()
                }
                listing_title = (
                    await db.execute(select(Listing.title).where(Listing.id == transaction.listing_id))
                ).scalar_one_or_none() or "Canal"

                names = {m.sender_id: display_name(users.get(m.sender_id)) for m in rows}
                history = [
                    {
                        "role": ROLE_LABELS.get(m.sender_role, m.sender_role),
                        "name": "" if m.sender_role in ("system", "assistant") else names.get(m.sender_id, ""),
                        "content": m.content,
                    }
                    for m in rows
                ]

                buyer, seller = users.get(transaction.buyer_id), users.get(transaction.seller_id)
                provider = "GRAM (blockchain TON)" if (transaction.currency or "").upper() == "GRAM" else "JessiKaPay (FCFA)"
                context = logic.build_context(
                    reference=transaction.reference,
                    status=transaction.status,
                    payment=provider,
                    price=f"{transaction.total_buyer_amount} {transaction.currency}",
                    listing_title=listing_title,
                    buyer=display_name(buyer),
                    seller=display_name(seller),
                    buyer_lang=getattr(buyer, "language", "fr"),
                    seller_lang=getattr(seller, "language", "fr"),
                    assistant_count=sent,
                    admin_name=display_name(users.get(transaction.assigned_admin_id)) if transaction.assigned_admin_id else None,
                )

                raw = await _call_llm(logic.SYSTEM_PROMPT, logic.build_user_prompt(context, history, trigger))
                out = logic.parse_model_output(raw)
                reply, blocked = logic.guard_reply(out["reply"], transaction.status)

                escalate, reason = out["escalate"], out["escalate_reason"]
                if blocked:
                    escalate, reason = True, f"Réponse de l'assistant bloquée par le garde-fou ({blocked})."

                if reply:
                    await post_assistant_message(db, transaction, reply)
                if escalate:
                    await _alert_admins(db, transaction, listing_title, reason or "L'assistant demande un humain.")
        except Exception:  # noqa: BLE001
            logger.exception("Assistant : échec sur la transaction %s", transaction_id)


async def _alert_admins(db, transaction: Transaction, listing_title: str, reason: str) -> None:
    """Prévient l'administrateur ; si l'accord de transfert est attendu, bouton direct."""

    previous = _last_alert.get(transaction.id)
    if previous and previous[0] == reason and time.time() - previous[1] < 600:
        return
    _last_alert[transaction.id] = (reason, time.time())

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    if transaction.status == "waiting_admin":
        rows.append([InlineKeyboardButton("✅ Autoriser le transfert", callback_data=f"assist_ok:{transaction.id}")])
    rows.append([InlineKeyboardButton("↩️ Écrire dans la discussion", callback_data=f"chat:{transaction.id}")])
    markup = InlineKeyboardMarkup(rows)

    text = (
        f"🤖 L'assistant demande un humain — {listing_title}\n\n"
        f"Transaction : {transaction.reference} (statut : {transaction.status})\n"
        f"Raison : {reason}\n\n"
        "Vous seul pouvez autoriser le transfert du canal."
    )
    for chat_id in await _admin_targets(db, transaction):
        try:
            notify_telegram(int(chat_id), text, markup)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alerte admin impossible : %s", exc)
