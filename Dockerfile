FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# On copie depuis la racine du contexte (qui est déjà le dossier backend)
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "echo '[nexmarket] conteneur lance' && python check_env.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
