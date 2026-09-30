from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_db, init_db

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


# ============================================================
# LIFESPAN
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    yield

    await close_db()


# ============================================================
# APPLICATION
# ============================================================


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Backend API de NexMarket, "
        "marketplace sécurisé pour la vente "
        "de chaînes Telegram."
    ),
    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTERS
# ============================================================


app.include_router(
    auth.router,
)

app.include_router(
    users.router,
)

app.include_router(
    wallet.router,
)

app.include_router(
    channels.router,
)

app.include_router(
    listings.router,
)

app.include_router(
    transactions.router,
)

app.include_router(
    messages.router,
)

app.include_router(
    reviews.router,
)

app.include_router(
    favorites.router,
)

app.include_router(
    reports.router,
)

app.include_router(
    admin.router,
)

app.include_router(
    deposits.router,
)

app.include_router(
    withdrawals.router,
)

app.include_router(
    webhooks.router,
)


# ============================================================
# ROOT
# ============================================================


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "online",
    }


# ============================================================
# HEALTH CHECK
# ============================================================


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
    }
