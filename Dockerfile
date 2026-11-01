# =========================================================
# NEXMARKET BACKEND - Dockerfile (à la racine du dépôt)
# =========================================================

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# On copie le fichier requirements.txt depuis le dossier backend
COPY backend/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# On copie tout le contenu du dossier backend (y compris check_env.py et le dossier app) dans /app
COPY backend/ .

EXPOSE 8000

# Le dossier app et check_env.py étant maintenant directement dans /app,
# l'exécution fonctionnera parfaitement.
CMD ["sh", "-c", "echo '[nexmarket] conteneur lance' && python check_env.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
