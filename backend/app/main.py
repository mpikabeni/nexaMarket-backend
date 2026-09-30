from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import init_db, close_db
from app.routes import admin,auth,channels,deposits,favorites,listings,messages,reports,transactions,users,wallet,withdrawals,webhooks
@asynccontextmanager
async def lifespan(app):
    await init_db(); yield; await close_db()
app=FastAPI(title=settings.APP_NAME,version=settings.APP_VERSION,lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins_list,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
for r in [auth,users,wallet,channels,listings,transactions,messages,reports,favorites,admin,deposits,withdrawals,webhooks]: app.include_router(r.router,prefix="/api")
@app.get("/")
async def root(): return {"app":"NexMarket","status":"online","version":settings.APP_VERSION}
@app.get("/health")
async def health(): return {"status":"healthy","service":"NexMarket API"}
