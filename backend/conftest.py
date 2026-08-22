"""Conftest pytest: ambiente isolato per i test (Fase 5).

Imposta le env vars PRIMA dell'import di qualsiasi modulo applicativo,
così config.py legge i valori di test invece del .env reale.
"""
import os
import sys
import tempfile

# Deve avvenire prima di ogni import di moduli backend
os.environ["ALLOW_INSECURE"] = "1"
os.environ["API_SECRET_KEY"] = ""
os.environ["CHECKPOINT_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="agent_test_"), "test_checkpoints.db")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
