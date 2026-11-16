"""Paiement en GRAM (TON) : détection des paiements et libération par l'admin.

Principe (aucune clé privée sur le serveur) :
1. L'acheteur envoie le prix en GRAM à l'adresse de NexMarket, avec le
   commentaire unique de sa transaction.
2. Le serveur LIT la blockchain : dès que le virement (bon commentaire, bon
   montant, réussi) est arrivé, la transaction passe en escrow comme un achat
   par wallet (discussion ouverte, transfert du canal, période de protection).
3. À la fin, l'administrateur envoie lui-même les GRAM au vendeur (prix moins
   5 %) depuis son portefeuille et garde la commission ; il saisit ensuite le
   hash de l'envoi dans la console : le serveur le vérifie sur la blockchain
   avant de clôturer. Même principe pour un remboursement.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.models.transaction import Transaction
from app.services import ton
from app.services.chat_service import open_transaction_chat
from app.services.notification_service import notify_admins

logger = logging.getLogger("nexmarket.gram")

ALERT_RELEASE = "[alerte-libération-envoyée]"
ALERT_REFUND = "[alerte-remboursement-envoyée]"
LATE_WINDOW = timedelta(hours=48)


class GramError(Exception):
    pass


def enabled() -> bool:
    return ton.is_valid_address(settings.GRAM_RECEIVE_ADDRESS or "")


def payment_info(transaction: Transaction) -> dict | None:
    """Instructions de paiement pour l'acheteur (transaction GRAM en attente)."""

    if (transaction.currency or "").upper() != "GRAM":
        return None
    if transaction.payment_status == "completed" or not enabled():
        return None
    amount = Decimal(str(transaction.total_buyer_amount))
    comment = transaction.payment_reference or ""
    return {
        "address": settings.GRAM_RECEIVE_ADDRESS.strip(),
        "amount": float(amount),
        "comment": comment,
        "link": ton.payment_link(settings.GRAM_RECEIVE_ADDRESS.strip(), amount, comment),
    }


def _note(transaction: Transaction, marker: str) -> bool:
    return marker in (transaction.admin_note or "")


def _add_note(transaction: Transaction, text: str) -> None:
    transaction.admin_note = ((transaction.admin_note or "") + "\n" + text).strip()


# ------------------------------------------------------------ paiements entrants
async def _mark_paid(db, transaction: Transaction, found: dict) -> None:
    now = datetime.now(timezone.utc)
    transaction.gram_tx_hash = found["hash"]
    transaction.payment_status = "completed"
    transaction.payment_confirmed_at = now
    transaction.escrow_held = True
    transaction.escrow_held_at = now
    transaction.status = "waiting_admin"
    await db.commit()
    await db.refresh(transaction)
    logger.info("GRAM reçu pour %s (%s GRAM, tx %s)", transaction.reference, found["amount"], found["hash"])
    try:
        await open_transaction_chat(db, transaction)
    except Exception:  # noqa: BLE001  l'achat reste valide
        await db.rollback()
    await notify_admins(
        db,
        "💎 Paiement GRAM reçu\n\n"
        f"Transaction : {transaction.reference}\n"
        f"Montant : {found['amount']} GRAM\n"
        f"Hash : {found['hash']}\n\n"
        "Vérifiez aussi dans votre portefeuille, puis prenez en charge le transfert du canal.",
    )


async def confirm_pending_payments(session_factory) -> int:
    """Constate les paiements GRAM arrivés. Renvoie le nombre confirmé."""

    if not enabled():
        return 0

    async with session_factory() as db:
        pending = (
            await db.execute(
                select(Transaction).where(
                    Transaction.payment_provider == "gram",
                    Transaction.status == "pending_payment",
                    Transaction.payment_status != "completed",
                ).limit(50)
            )
        ).scalars().all()
        late = (
            await db.execute(
                select(Transaction).where(
                    Transaction.payment_provider == "gram",
                    Transaction.status == "cancelled",
                    Transaction.gram_tx_hash.is_(None),
                    Transaction.created_at > datetime.now(timezone.utc) - LATE_WINDOW,
                ).limit(50)
            )
        ).scalars().all()

        if not pending and not late:
            return 0

        try:
            txs = await ton.fetch_transactions(settings.GRAM_RECEIVE_ADDRESS.strip())
        except Exception as exc:  # réseau / API : on réessaiera
            logger.warning("Lecture blockchain impossible : %s", exc)
            return 0

        done = 0
        for transaction in pending:
            found = ton.find_incoming_payment(
                txs,
                my_address=settings.GRAM_RECEIVE_ADDRESS,
                comment=transaction.payment_reference or "\x00",
                min_amount=transaction.total_buyer_amount,
            )
            if not found or not found.get("hash"):
                continue
            # Un même virement ne peut jamais payer deux transactions.
            used = (
                await db.execute(
                    select(Transaction.id).where(Transaction.gram_tx_hash == found["hash"])
                )
            ).first()
            if used:
                continue
            await _mark_paid(db, transaction, found)
            done += 1

        # Paiement arrivé APRÈS l'expiration : l'argent est chez NexMarket,
        # il doit être remboursé (tâche « remboursement » + alerte).
        for transaction in late:
            found = ton.find_incoming_payment(
                txs,
                my_address=settings.GRAM_RECEIVE_ADDRESS,
                comment=transaction.payment_reference or "\x00",
                min_amount=transaction.total_buyer_amount,
            )
            if not found or not found.get("hash"):
                continue
            used = (
                await db.execute(
                    select(Transaction.id).where(Transaction.gram_tx_hash == found["hash"])
                )
            ).first()
            if used:
                continue
            transaction.gram_tx_hash = found["hash"]
            transaction.escrow_held = True
            _add_note(transaction, f"Paiement GRAM tardif reçu (hash {found['hash']}) : à rembourser.")
            await db.commit()

        return done


# ------------------------------------------------------------ alertes admin
def release_amounts(transaction: Transaction) -> tuple[Decimal, Decimal]:
    return Decimal(str(transaction.seller_amount)), Decimal(str(transaction.platform_fee))


async def alert_pending_tasks(session_factory) -> int:
    """Prévient les admins (une fois) des GRAM à libérer / rembourser."""

    sent = 0
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(Transaction).where(
                    Transaction.payment_provider == "gram",
                    Transaction.escrow_held.is_(True),
                    Transaction.status.in_(("completed", "refunded", "cancelled")),
                ).limit(50)
            )
        ).scalars().all()
        for t in rows:
            if t.status == "completed" and not _note(t, ALERT_RELEASE):
                to_seller, fee = release_amounts(t)
                await notify_admins(
                    db,
                    "💎 GRAM à LIBÉRER\n\n"
                    f"Transaction : {t.reference}\n"
                    f"Envoyez {to_seller} GRAM au vendeur :\n{t.seller_gram_address}\n"
                    f"(commission de {fee} GRAM : vous la gardez)\n\n"
                    "Puis saisissez le hash de l'envoi dans la console (onglet GRAM).",
                )
                _add_note(t, ALERT_RELEASE)
                await db.commit()
                sent += 1
            elif t.status in ("refunded", "cancelled") and not _note(t, ALERT_REFUND):
                await notify_admins(
                    db,
                    "💎 GRAM à REMBOURSER\n\n"
                    f"Transaction : {t.reference}\n"
                    f"Renvoyez {t.total_buyer_amount} GRAM à l'acheteur :\n{t.buyer_gram_address}\n\n"
                    "Puis saisissez le hash de l'envoi dans la console (onglet GRAM).",
                )
                _add_note(t, ALERT_REFUND)
                await db.commit()
                sent += 1
    return sent


# ------------------------------------------------------------ actions admin
async def list_tasks(db) -> list[dict]:
    rows = (
        await db.execute(
            select(Transaction).where(
                Transaction.payment_provider == "gram",
                Transaction.escrow_held.is_(True),
                Transaction.status.in_(("completed", "refunded", "cancelled")),
            ).order_by(Transaction.id.desc()).limit(100)
        )
    ).scalars().all()
    tasks = []
    for t in rows:
        if t.status == "completed":
            to_seller, fee = release_amounts(t)
            tasks.append({"id": t.id, "reference": t.reference, "kind": "release",
                          "address": t.seller_gram_address, "amount": float(to_seller),
                          "commission": float(fee), "paid_in_hash": t.gram_tx_hash})
        else:
            tasks.append({"id": t.id, "reference": t.reference, "kind": "refund",
                          "address": t.buyer_gram_address, "amount": float(t.total_buyer_amount),
                          "commission": 0.0, "paid_in_hash": t.gram_tx_hash})
    return tasks


async def mark_sent(db, transaction_id: int, admin_id: int, tx_hash: str, *, unverified: bool = False) -> Transaction:
    """L'admin a envoyé les GRAM (libération ou remboursement) : on vérifie et on clôt."""

    transaction = (
        await db.execute(
            select(Transaction).where(Transaction.id == transaction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if transaction is None or transaction.payment_provider != "gram":
        raise GramError("Transaction GRAM introuvable.")
    if not transaction.escrow_held:
        raise GramError("Cette transaction est déjà clôturée.")
    if transaction.status not in ("completed", "refunded", "cancelled"):
        raise GramError("Cette transaction n'est pas prête : terminez-la (ou remboursez-la) d'abord.")

    tx_hash = (tx_hash or "").strip()
    if len(tx_hash) < 8:
        raise GramError("Saisissez le hash de la transaction d'envoi.")
    reused = (
        await db.execute(
            select(Transaction.id).where(Transaction.gram_release_tx_hash == tx_hash)
        )
    ).first()
    if reused:
        raise GramError("Ce hash a déjà servi pour une autre transaction.")

    release = transaction.status == "completed"
    to_addr = transaction.seller_gram_address if release else transaction.buyer_gram_address
    amount = transaction.seller_amount if release else transaction.total_buyer_amount

    if not unverified:
        try:
            txs = await ton.fetch_transactions(settings.GRAM_RECEIVE_ADDRESS.strip(), limit=200)
        except Exception as exc:  # noqa: BLE001
            raise GramError(f"Blockchain injoignable ({exc}). Réessayez, ou confirmez sans vérification.") from exc
        found = ton.find_outgoing_payment(txs, to_address=to_addr, min_amount=amount, tx_hash=tx_hash)
        if not found:
            raise GramError(
                f"Envoi introuvable sur la blockchain : il faut {amount} GRAM vers {to_addr} avec ce hash."
            )

    now = datetime.now(timezone.utc)
    transaction.gram_release_tx_hash = tx_hash
    transaction.escrow_held = False
    if release:
        transaction.seller_paid_at = now
    else:
        transaction.refunded_at = now
    _add_note(
        transaction,
        f"GRAM {'libérés' if release else 'remboursés'} par l'admin #{admin_id} (hash {tx_hash})"
        + (" — NON vérifié sur la blockchain" if unverified else ""),
    )
    await db.commit()
    await db.refresh(transaction)
    return transaction
