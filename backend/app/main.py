# backend/app/main.py

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db

from app.routes import (
    auth,
    users,
    wallet,
    channels,
    listings,
    transactions,
    messages,
    admin,
    reports,
    favorites,
    reviews,
)


# =========================================================
# LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    # Initialisation de la base de données
    init_db()

    yield


# =========================================================
# APPLICATION
# =========================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "API officielle de NexMarket, "
        "marketplace dédiée aux canaux Telegram."
    ),
    docs_url=(
        "/docs"
        if settings.ENVIRONMENT != "production"
        else None
    ),
    redoc_url=(
        "/redoc"
        if settings.ENVIRONMENT != "production"
        else None
    ),
    openapi_url=(
        "/openapi.json"
        if settings.ENVIRONMENT != "production"
        else None
    ),
    lifespan=lifespan,
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Telegram-Init-Data",
    ],
)


# =========================================================
# API ROUTES
# =========================================================

app.include_router(
    auth.router,
    prefix="/api",
)

app.include_router(
    users.router,
    prefix="/api",
)

app.include_router(
    wallet.router,
    prefix="/api",
)

app.include_router(
    channels.router,
    prefix="/api",
)

app.include_router(
    listings.router,
    prefix="/api",
)

app.include_router(
    transactions.router,
    prefix="/api",
)

app.include_router(
    messages.router,
    prefix="/api",
)

app.include_router(
    admin.router,
    prefix="/api",
)

app.include_router(
    reports.router,
    prefix="/api",
)

app.include_router(
    favorites.router,
    prefix="/api",
)

app.include_router(
    reviews.router,
    prefix="/api",
)


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {
        "app": "NexMarket",
        "service": "API",
        "status": "online",
        "version": settings.APP_VERSION,
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "NexMarket API",
    }


@app.get("/api/health")
def api_health():

    return {
        "status": "healthy",
        "service": "NexMarket API",
        "database": "configured",
        "telegram": "configured"
        if settings.TELEGRAM_BOT_TOKEN
        else "not_configured",
        "moneyfusion": "configured"
        if settings.MONEYFUSION_API_URL
        else "not_configured",
    }