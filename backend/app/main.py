import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.bot import build_application
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
    reports,
    reviews,
    transactions,
    users,
    wallet,
    webhooks,
    withdrawals,
)
from app.services.jessikapay import JessiKaPayError
from app.services.transaction_service import (
    TransactionService,
    TransactionServiceError,
)
from app.services.wallet_service import WalletServiceError

logger = logging.getLogger("nexmarket")

EXPIRE_INTERVAL_SECONDS = 300

telegram_application = None


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

        await application.updater.start_polling(drop_pending_updates=True)

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
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_application

    await init_db()

    telegram_application = await _start_bot()

    expire_task = asyncio.create_task(_maintenance_loop())

    try:
        yield

    finally:
        expire_task.cancel()

        try:
            await expire_task
        except asyncio.CancelledError:
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
    favorites,
    admin,
    deposits,
    withdrawals,
    webhooks,
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
        "status": "healthy",
        "service": "NexMarket API",
        "telegram_bot": (
            "running" if telegram_application is not None else "stopped"
        ),
    }
