# =========================================================
# NEXMARKET BACKEND - Dockerfile (version minimale et robuste)
# =========================================================

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# UN SEUL worker : le bot Telegram tourne en polling dans l'API.
# Les messages [nexmarket] permettent de voir, dans l'onglet Logs de
# Render, jusqu'où le démarrage va :
#   1) conteneur lancé  2) variables OK  3) serveur uvicorn
# (l'import de l'application n'est plus fait deux fois : sur une petite
# instance gratuite, cela doublait le temps de démarrage.)
CMD ["sh", "-c", "echo '[nexmarket] conteneur lance' && python check_env.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
