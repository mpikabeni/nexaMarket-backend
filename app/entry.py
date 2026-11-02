"""
Point d'entrée de l'API (uvicorn app.entry:app).

Si l'application ne peut pas démarrer (variable d'environnement manquante
ou invalide, import cassé...), au lieu de mourir en silence (le service
redémarre en boucle et la Mini App n'affiche que « Not Found » ou « trop de
temps »), un petit serveur de DIAGNOSTIC démarre et répond partout :

    GET /health  ->  503 {"status": "error", "detail": "<cause exacte>"}

Il suffit alors d'ouvrir https://<votre-api>/health dans un navigateur.
Aucune valeur secrète n'est affichée (uniquement le nom du champ et la règle).
"""

import logging

logger = logging.getLogger("nexmarket.entry")


def _safe_reason(exc: BaseException) -> str:
    """Description de l'erreur SANS valeurs (une ValidationError Pydantic
    contient normalement la valeur saisie : jamais affichée ici)."""

    errors = getattr(exc, "errors", None)

    if callable(errors):
        try:
            parts = [
                f"{'.'.join(str(p) for p in item.get('loc', ())) or 'config'}"
                f" : {item.get('msg', 'invalide')}"
                for item in errors()
            ]
            return " ; ".join(parts)[:500]
        except Exception:
            pass

    return f"{type(exc).__name__} : {str(exc)[:300]}"


try:
    from app.main import app  # noqa: F401

except Exception as exc:  # démarrage impossible -> mode diagnostic
    logger.exception("Démarrage de NexMarket impossible")

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    reason = _safe_reason(exc)

    app = FastAPI(title="NexMarket (mode diagnostic)")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def diagnostic(path: str):
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": f"Le serveur n'a pas pu démarrer : {reason}",
            },
        )
