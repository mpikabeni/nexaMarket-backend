FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# On se place dans le dossier backend
WORKDIR /app/backend

# On force les dossiers à être des modules Python
RUN touch app/__init__.py && touch app/models/__init__.py && touch app/routes/__init__.py && touch app/services/__init__.py

EXPOSE 8000

CMD ["sh", "-c", "echo '[nexmarket] conteneur lance' && cd /app && python check_env.py || echo 'check_env non trouvé' && cd /app/backend && python -c 'import app.main; print(\"[nexmarket] import app.main OK\")' && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
