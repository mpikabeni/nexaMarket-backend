# =========================================================
# NEXMARKET BACKEND - Dockerfile (version corrigée)
# =========================================================

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# On copie d'abord les fichiers de configuration et les dépendances situés dans le dossier backend
COPY backend/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# On copie tout le contenu du dossier backend dans /app du conteneur
COPY backend/ .

EXPOSE 8000

# Le dossier 'app' étant maintenant directement dans /app,
# 'app.main:app' sera parfaitement trouvé par uvicorn.
CMD ["sh", "-c", "echo '[nexmarket] conteneur lance' && python check_env.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
