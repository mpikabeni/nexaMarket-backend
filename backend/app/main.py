from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db, close_db

from app.routes import (
    admin,
    auth,
    channels,
    deposits,
    favorites,
    listings,
    messages,
    reports,
    transactions,
    users,
    wallet,
    withdrawals,
    webhooks,
)

from app.bot import build_application


# ============================================================
# TELEGRAM BOT
# ============================================================

telegram_application = None


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_application

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    await init_db()

    # --------------------------------------------------------
    # TELEGRAM BOT
    # --------------------------------------------------------

    telegram_application = build_application()

    try:
        await telegram_application.initialize()

        await telegram_application.start()

        if telegram_application.updater is None:
            raise RuntimeError(
                "Le Telegram Updater n'est pas disponible."
            )

        await telegram_application.updater.start_polling(
            drop_pending_updates=True
        )

        print("==========================================")
        print("NexMarket Telegram bot démarré")
        print("Telegram polling actif")
        print("==========================================")

        yield

    finally:

        # ----------------------------------------------------
        # ARRÊT TELEGRAM
        # ----------------------------------------------------

        if telegram_application is not None:

            try:
                if telegram_application.updater is not None:
                    await telegram_application.updater.stop()
            except Exception as exc:
                print(
                    f"Erreur arrêt Telegram updater : {exc}"
                )

            try:
                await telegram_application.stop()
            except Exception as exc:
                print(
                    f"Erreur arrêt Telegram application : {exc}"
                )

            try:
                await telegram_application.shutdown()
            except Exception as exc:
                print(
                    f"Erreur shutdown Telegram : {exc}"
                )

        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        await close_db()


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# API ROUTES
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
    favorites,
    admin,
    deposits,
    withdrawals,
    webhooks,
]:
    app.include_router(
        router_module.router,
        prefix="/api",
    )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    return {
        "app": "NexMarket",
        "status": "online",
        "version": settings.APP_VERSION,
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "NexMarket API",
        "telegram_bot": (
            "running"
            if telegram_application is not None
            else "stopped"
        ),
    }
