FROM python:3.12-slim

WORKDIR /app

# Copier le fichier des dépendances depuis la racine
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copier TOUT le contenu du dépôt (racine) dans /app
COPY . .

EXPOSE 8000

# Commande de démarrage (à adapter selon votre point d'entrée, ex: main:app ou app.main:app)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
