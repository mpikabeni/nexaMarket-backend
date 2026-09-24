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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise les tables au démarrage
    init_db()
    yield


# IMPORTANT : l'application doit être créée AVANT include_router()
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTES API
# ============================================================

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(wallet.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(listings.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def root():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "nexmarket-api",
    }


@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "service": "nexmarket-api",
    }
