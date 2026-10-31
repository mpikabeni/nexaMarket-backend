"""
Contrôle de démarrage (bibliothèque standard uniquement).

Affiche en clair, dans les logs Render, ce qui manque ou est invalide AVANT
le lancement de l'API. Ne montre jamais la valeur d'un secret.
"""

import os
import sys

REQUIRED = {
    "DATABASE_URL": "URL PostgreSQL (Render : propriété connectionString de la base)",
    "TELEGRAM_BOT_TOKEN": "token du bot, donné par @BotFather",
    "JWT_SECRET": "chaîne secrète d'au moins 32 caractères",
}

OPTIONAL = [
    "ADMIN_CODE",
    "ADMIN_TELEGRAM_ID",
    "JESSIKAPAY_API_URL",
    "JESSIKAPAY_API_KEY",
    "JESSIKAPAY_API_SECRET",
    "JESSIKAPAY_WEBHOOK_SECRET",
    "NEXA_JP_NUMBER",
    "TELEGRAM_BOT_USERNAME",
    "CORS_ORIGINS",
]

problems = []

for name, help_text in REQUIRED.items():
    value = os.environ.get(name, "").strip()

    if not value:
        problems.append(f"{name} est absente ou vide ({help_text}).")
    elif name == "JWT_SECRET" and len(value) < 32:
        problems.append(
            f"JWT_SECRET est trop courte ({len(value)} caractères, 32 minimum)."
        )
    elif name == "DATABASE_URL" and not value.startswith(
        ("postgres://", "postgresql://", "postgresql+asyncpg://")
    ):
        problems.append(
            "DATABASE_URL doit commencer par postgresql:// ou postgres://."
        )

admin_id = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
if admin_id and not admin_id.lstrip("-").isdigit():
    problems.append("ADMIN_TELEGRAM_ID doit être un nombre (votre ID Telegram).")

print("[check_env] variables optionnelles :", flush=True)
for name in OPTIONAL:
    state = "définie" if os.environ.get(name, "").strip() else "non définie"
    print(f"[check_env]   {name}: {state}", flush=True)

if problems:
    print("[check_env] ERREUR - l'API ne peut pas démarrer :", flush=True)
    for line in problems:
        print(f"[check_env]   - {line}", flush=True)
    sys.exit(1)

print("[check_env] configuration OK", flush=True)
