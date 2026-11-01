"""
Compatibilité : l'ancien module dupliquait tout le client JessiKaPay
avec une classe JessiKaPayError différente (donc des `except` qui ne
rattrapaient rien). Il n'existe plus qu'UN client : app/services/jessikapay.py
"""

from app.services.jessikapay import (  # noqa: F401
    JessiKaPayError,
    JessiKaPayService,
    jessikapay_service,
)
