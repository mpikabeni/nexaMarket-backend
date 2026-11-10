import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.bot import BOT_ALLOWED_UPDATES, build_application
from app.config import settings
from app.db import AsyncSessionLocal, close_db, init_db
from app.routes import (
    admin,
    auth,
    channels,
    deposits,
    favorites,
    listings,
    messages,
    rates,
    reports,
    reviews,
    stats,
    transactions,
    users,
    wallet,
    withdrawals,
)
from app.services.commission_service import settle_pending_commissions
from app.services.deposit_sync import sync_pending_deposits
from app.services.jessikapay import JessiKaPayError
from app.services.transaction_service import (
    TransactionService,
    TransactionServiceError,
)
from app.services.wallet_service import WalletServiceError

logger = logging.getLogger("nexmarket")

EXPIRE_INTERVAL_SECONDS = 300
DEPOSIT_SYNC_INTERVAL_SECONDS = 15

telegram_application = None
db_ready = False
db_error = ""


# ============================================================
# TÂCHES DE FOND (toutes les 5 minutes)
#   - libère les annonces réservées mais jamais payées ;
#   - verse automatiquement le vendeur quand la période de
#     protection est terminée sans litige.
# ============================================================

async def _maintenance_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as db:
                expired = await TransactionService(db).expire_unpaid(
                    settings.PENDING_PAYMENT_TTL_MINUTES
                )

            async with AsyncSessionLocal() as db:
                finished = await TransactionService(
                    db
                ).auto_finish_protections()

            if expired or finished:
                logger.info(
                    "Maintenance : %s expirée(s), %s clôturée(s)",
                    expired,
                    finished,
                )

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec de la tâche de maintenance")

        await asyncio.sleep(EXPIRE_INTERVAL_SECONDS)


# ============================================================
# VÉRIFICATION DES DÉPÔTS (remplace le webhook JessiKaPay)
# ============================================================

async def _deposit_sync_loop() -> None:
    while True:
        try:
            credited = await sync_pending_deposits(AsyncSessionLocal)

            if credited:
                logger.info("%s dépôt(s) crédité(s)", credited)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec de la vérification des dépôts")

        await asyncio.sleep(DEPOSIT_SYNC_INTERVAL_SECONDS)


# ============================================================
# VERSEMENT DES COMMISSIONS vers le compte JessiKaPay NexMarket
# ============================================================

async def _commission_loop() -> None:
    while True:
        try:
            sent = await settle_pending_commissions(AsyncSessionLocal)

            if sent:
                logger.info("%s commission(s) versée(s)", sent)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec du versement des commissions")

        await asyncio.sleep(20)


# ============================================================
# TELEGRAM BOT
# ============================================================

async def _start_bot():
    """
    Un bot indisponible (token invalide, Telegram injoignable...) ne
    doit PAS empêcher l'API de démarrer (avant : toute l'API tombait).
    """

    application = build_application()

    try:
        await application.initialize()
        await application.start()

        if application.updater is None:
            raise RuntimeError("Le Telegram Updater n'est pas disponible.")

        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=BOT_ALLOWED_UPDATES,
            timeout=25,
        )

        logger.info("Telegram bot démarré (polling actif)")
        return application

    except Exception:
        logger.exception("Démarrage du bot Telegram impossible")

        try:
            await application.shutdown()
        except Exception:
            pass

        return None


async def _stop_bot(application) -> None:
    for step in (
        lambda: application.updater.stop() if application.updater else None,
        application.stop,
        application.shutdown,
    ):
        try:
            result = step()

            if result is not None:
                await result
        except Exception as exc:
            logger.warning("Erreur à l'arrêt du bot : %s", exc)


# ============================================================
# BASE DE DONNÉES : initialisation tolérante
# ============================================================
# Avant, un échec de init_db() au démarrage faisait tomber TOUT le service
# (redémarrages en boucle, « Not Found » dans la Mini App). Maintenant l'API
# démarre, réessaie toutes les 10 s, et /health indique l'état.

async def _init_db_with_retry() -> None:
    global db_ready, db_error

    while True:
        try:
            await init_db()
            db_ready = True
            db_error = ""
            logger.info("Base de données prête")
            return

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            db_error = type(exc).__name__
            logger.exception("Base de données indisponible, nouvel essai dans 10 s")
            await asyncio.sleep(10)


# ============================================================
# SURVEILLANCE DU BOT
# ============================================================
# Le bot démarre EN ARRIÈRE-PLAN (l'API répond tout de suite, même si
# Telegram est lent) et il est relancé automatiquement s'il s'arrête.

async def _bot_supervisor() -> None:
    global telegram_application

    while True:
        try:
            if telegram_application is None:
                telegram_application = await _start_bot()
                await asyncio.sleep(10 if telegram_application is None else 30)
                continue

            updater = telegram_application.updater

            if updater is None or not updater.running:
                logger.warning("Le bot Telegram s'est arrêté : redémarrage")
                await _stop_bot(telegram_application)
                telegram_application = None
                continue

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erreur du superviseur du bot")

        await asyncio.sleep(30)


# ============================================================
# KEEP-ALIVE (hébergement gratuit)
# ============================================================
# Un service web Render gratuit s'endort après ~15 min SANS requête
# entrante. Le bot en « polling » ne compte pas : il cessait donc de
# répondre. On se contacte soi-même via l'URL publique (compte comme une
# requête entrante). Pour une fiabilité totale : offre payante, ou un
# moniteur externe (UptimeRobot) sur /health.

async def _keepalive_loop() -> None:
    base = (
        settings.PUBLIC_URL or os.environ.get("RENDER_EXTERNAL_URL", "")
    ).rstrip("/")

    if not base:
        logger.info("Keep-alive désactivé (URL publique inconnue)")
        return

    url = f"{base}/health"

    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            await asyncio.sleep(8 * 60)

            try:
                await client.get(url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Keep-alive : %s", exc)


# ============================================================
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_task = asyncio.create_task(_init_db_with_retry())

    try:
        # On attend un peu pour que les premières requêtes trouvent les
        # tables, mais sans bloquer le démarrage si la base tarde.
        await asyncio.wait_for(asyncio.shield(db_task), timeout=8)
    except asyncio.TimeoutError:
        logger.warning("Base de données encore en cours d'initialisation")
    except Exception:
        pass

    tasks = [
        db_task,
        asyncio.create_task(_bot_supervisor()),
        asyncio.create_task(_maintenance_loop()),
        asyncio.create_task(_deposit_sync_loop()),
        asyncio.create_task(_commission_loop()),
        asyncio.create_task(_keepalive_loop()),
    ]

    try:
        yield

    finally:
        for task in tasks:
            task.cancel()

        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        if telegram_application is not None:
            await _stop_bot(telegram_application)

        await close_db()


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# Garde-fou : un traitement qui dépasse 28 s est interrompu avec une réponse
# claire (504). Sans cela la Mini App attendait sans savoir si le serveur
# plantait ou était simplement lent. (Ajouté en premier = le plus interne.)
@app.middleware("http")
async def request_timeout(request: Request, call_next):
    try:
        return await asyncio.wait_for(call_next(request), timeout=28)

    except asyncio.TimeoutError:
        logger.error(
            "Requête trop lente (>28 s) : %s %s",
            request.method,
            request.url.path,
        )

        return JSONResponse(
            status_code=504,
            content={
                "detail": (
                    "Le serveur a mis trop de temps à traiter la demande "
                    f"({request.method} {request.url.path}). Réessaie."
                )
            },
        )


# Réponses JSON compressées (liste d'annonces, etc.) : plus rapide en 3G/4G.
app.add_middleware(GZipMiddleware, minimum_size=800)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ERREURS MÉTIER
# ============================================================
# Avant : TransactionServiceError / WalletServiceError / JessiKaPayError
# n'étaient attrapées nulle part, donc chaque refus métier ("annonce
# indisponible", "solde insuffisant"...) sortait en HTTP 500.

@app.exception_handler(TransactionServiceError)
async def transaction_error_handler(request: Request, exc: TransactionServiceError):
    message = str(exc)
    code = 404 if "introuvable" in message.lower() else 400
    return JSONResponse(status_code=code, content={"detail": message})


@app.exception_handler(WalletServiceError)
async def wallet_error_handler(request: Request, exc: WalletServiceError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(JessiKaPayError)
async def jessikapay_error_handler(request: Request, exc: JessiKaPayError):
    return JSONResponse(
        status_code=502,
        content={"detail": f"Erreur JessiKaPay : {exc}"},
    )


# ============================================================
# ROUTES
# ============================================================

for router_module in [
    auth,
    users,
    wallet,
    channels,
    listings,
    transactions,
    messages,
    reports,
    reviews,
    stats,
    rates,
    favorites,
    admin,
    deposits,
    withdrawals,
]:
    app.include_router(router_module.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "app": "NexMarket",
        "status": "online",
        "version": settings.APP_VERSION,
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy" if db_ready else "degraded",
        "service": "NexMarket API",
        "database": "ok" if db_ready else (db_error or "initialisation"),
        "telegram_bot": (
            "running" if telegram_application is not None else "stopped"
        ),
    }
