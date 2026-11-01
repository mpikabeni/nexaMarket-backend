FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# FIX : Force Python à reconnaitre 'app' comme module
RUN touch app/__init__.py || echo "pas de dossier app, on continue"
RUN ls -la && ls -la app/ || echo "ERREUR: dossier app/ introuvable à la racine !"

EXPOSE 8000

CMD ["sh", "-c", "echo '[nexmarket] conteneur lance' && python check_env.py && python -c 'import app.main; print(\"[nexmarket] import app.main OK\")' && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
