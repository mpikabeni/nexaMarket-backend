"""Assistant IA des transactions (Groq / Gemini, gratuits) : orchestration.

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
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_tasks: set[asyncio.Task] = set()
_locks: dict[int, asyncio.Lock] = {}
_last_alert: dict[int, tuple[str, float]] = {}


def _providers() -> list[str]:
    """Fournisseurs à essayer, dans l'ordre voulu, ceux qui ont une clé seulement."""
    keys = {
        "groq": settings.GROQ_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
    }
    order = [n.strip().lower() for n in (settings.ASSISTANT_PROVIDERS or "").split(",") if n.strip()]
    return [n for n in order if n in keys and (keys[n] or "").strip()]


def enabled() -> bool:
    return bool(_providers())


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


async def _chat_openai_compat(client: httpx.AsyncClient, url: str, key: str, model: str,
                              system: str, user_prompt: str) -> str:
    """Groq (format OpenAI chat/completions), clé en « Bearer »."""
    response = await client.post(
        url,
        headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
        json={
            "model": model,
            "max_tokens": 700,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


async def _chat_gemini(client: httpx.AsyncClient, key: str, model: str,
                       system: str, user_prompt: str) -> str:
    # La clé passe dans l'en-tête (pas dans l'URL) pour ne jamais apparaître dans les logs.
    response = await client.post(
        GEMINI_URL.format(model=model.strip()),
        headers={"x-goog-api-key": key.strip(), "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                # Marge large : la « réflexion » de certains modèles Gemini consomme ce plafond.
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        },
    )
    response.raise_for_status()
    candidates = response.json().get("candidates") or []
    if not candidates:  # requête bloquée par les filtres de Gemini
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(
        part.get("text", "") for part in parts if isinstance(part, dict) and not part.get("thought")
    )


async def _call_llm(system: str, user_prompt: str) -> str:
    """Essaie les fournisseurs gratuits à la suite : le premier qui répond gagne.

    Erreur, limite de débit (429), clé invalide ou réponse vide : on passe au suivant.
    Si tous échouent, une 2e passe est tentée après une courte pause.
    """

    providers = _providers()
    if not providers:
        raise RuntimeError("Aucune clé IA configurée (GROQ_API_KEY ou GEMINI_API_KEY).")

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for round_number in range(2):
            for name in providers:
                try:
                    if name == "groq":
                        text = await _chat_openai_compat(
                            client, GROQ_URL, settings.GROQ_API_KEY, settings.GROQ_MODEL, system, user_prompt)
                    else:
                        text = await _chat_gemini(
                            client, settings.GEMINI_API_KEY, settings.GEMINI_MODEL, system, user_prompt)
                    if not (text or "").strip():
                        raise RuntimeError("réponse vide")
                    logger.info("Assistant : réponse fournie par %s", name)
                    return text
                except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError, RuntimeError) as exc:
                    # On ne journalise que le type d'erreur / le code HTTP (jamais la clé ni l'URL complète).
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    logger.warning("Assistant : %s indisponible (%s)", name, status or type(exc).__name__)
                    last_error = exc
            if round_number == 0:
                await asyncio.sleep(4)
    raise RuntimeError(f"Appel à l'assistant impossible : {type(last_error).__name__ if last_error else 'inconnu'}")


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

                # Captures d'écran : le vendeur (transfert fait) puis l'acheteur (canal reçu).
                # Déclencheur côté serveur : la demande ne dépend pas du hasard du modèle.
                last = rows[-1] if rows else None
                if (
                    last is not None
                    and transaction.status in ("transfer_started", "protection_period")
                    and last.sender_role in ("seller", "buyer")
                ):
                    is_image = bool(last.attachment_file_id) and last.message_type in ("image", "document")
                    already_sent = any(
                        m.sender_role == last.sender_role and m.attachment_file_id for m in rows
                    )
                    text = last.content or ""
                    if last.sender_role == "seller" and transaction.status == "transfer_started":
                        if is_image:
                            trigger = logic.TRIGGER_SCREENSHOT_RECEIVED
                        elif not already_sent and logic.claims_transfer_done(text):
                            trigger = logic.TRIGGER_ASK_SCREENSHOT
                    elif last.sender_role == "buyer":
                        if is_image:
                            trigger = logic.TRIGGER_BUYER_SCREENSHOT_RECEIVED
                        elif not already_sent and logic.claims_received(text):
                            trigger = logic.TRIGGER_ASK_BUYER_SCREENSHOT

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
                provider = "GRAM (blockchain TON)" if (transaction.currency or "").upper() == "GRAM" else "Mobile Money (FCFA)"
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
