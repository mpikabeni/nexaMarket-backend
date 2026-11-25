"""Renforcement de la sécurité de l'API : limitation de débit, taille des
requêtes et en-têtes de sécurité.

Limiteur en mémoire (une instance). Si l'API tourne sur plusieurs
instances, chaque instance compte séparément : c'est déjà une protection
solide contre l'abus, sans dépendance externe.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings

# (méthode ou "*", préfixe de chemin sans /api) -> (requêtes, fenêtre en secondes)
RULES: list[tuple[str, str, int, int]] = [
    ("*", "/auth", 12, 60),                         # connexion
    ("POST", "/deposits/purchase", 6, 60),          # lancement d'un paiement
    ("POST", "/transactions", 10, 60),              # achat en GRAM
    ("POST", "/listings", 10, 60),                  # création d'annonce
    ("GET", "/listings/jp-lookup", 15, 60),         # anti-énumération des numéros JP
    ("POST", "/users/me/onboarding", 10, 60),
    ("POST", "/admin/wallets", 20, 60),             # ajustements de portefeuille
    ("POST", "/disputes", 10, 60),
]
DEFAULT_LIMIT = (300, 60)                           # tout le reste, par client
EXEMPT_PREFIXES = ("/webhooks", "/health")          # signés / sondes

_hits: dict[str, deque] = {}
_last_cleanup = 0.0


def client_ip(request: Request) -> str:
    """IP du client derrière le proxy : on prend l'entrée ajoutée par NOTRE
    proxy (la plus à droite), pas celle que le client peut falsifier."""

    hops = max(1, int(getattr(settings, "TRUSTED_PROXY_HOPS", 1) or 1))
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]

    if len(forwarded) >= hops:
        return forwarded[-hops]

    return request.client.host if request.client else "unknown"


def _identity(request: Request) -> str:
    """IP + empreinte du jeton : un utilisateur connecté a son propre quota."""

    ip = client_ip(request)
    auth = request.headers.get("authorization", "")

    if auth:
        return f"{ip}:{hashlib.sha256(auth.encode()).hexdigest()[:12]}"

    return ip


def _allowed(key: str, limit: int, window: int) -> tuple[bool, int]:
    now = time.monotonic()
    bucket = _hits.setdefault(key, deque())

    while bucket and now - bucket[0] > window:
        bucket.popleft()

    if len(bucket) >= limit:
        return False, max(1, int(window - (now - bucket[0])))

    bucket.append(now)
    return True, 0


def _cleanup() -> None:
    global _last_cleanup
    now = time.monotonic()

    if now - _last_cleanup < 120:
        return

    _last_cleanup = now

    for key in [k for k, v in _hits.items() if not v or now - v[-1] > 300]:
        _hits.pop(key, None)


def install(app: FastAPI) -> None:
    max_body = int(getattr(settings, "MAX_BODY_BYTES", 15 * 1024 * 1024))

    @app.middleware("http")
    async def security_layer(request: Request, call_next):
        path = request.url.path
        api_path = path[4:] if path.startswith("/api/") else path
        method = request.method.upper()

        if method != "OPTIONS" and not api_path.startswith(EXEMPT_PREFIXES):
            _cleanup()

            # 1) Taille maximale des requêtes
            try:
                length = int(request.headers.get("content-length") or 0)
            except ValueError:
                length = 0

            if length > max_body:
                return JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)

            # 2) Limitation de débit : règle précise puis règle générale
            ident = _identity(request)

            for rule_method, prefix, limit, window in RULES:
                if (rule_method in ("*", method)) and api_path.startswith(prefix):
                    ok, retry = _allowed(f"{rule_method}{prefix}:{ident}", limit, window)

                    if not ok:
                        return JSONResponse(
                            {"detail": "Trop de tentatives. Patiente un instant puis réessaie."},
                            status_code=429,
                            headers={"Retry-After": str(retry)},
                        )
                    break

            ok, retry = _allowed(f"all:{ident}", *DEFAULT_LIMIT)

            if not ok:
                return JSONResponse(
                    {"detail": "Trop de requêtes. Patiente un instant."},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )

        response = await call_next(request)

        # 3) En-têtes de sécurité
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        if api_path.startswith(("/auth", "/users", "/wallet", "/admin", "/transactions", "/deposits")):
            response.headers["Cache-Control"] = "no-store"

        return response
