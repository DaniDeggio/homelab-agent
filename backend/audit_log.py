"""Audit log persistente di ogni tool call (Fase 0.4)."""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import config

logger = logging.getLogger("audit_log")


def _get_conn():
    return sqlite3.connect(config.CHECKPOINT_DB_PATH)


def init_audit_db():
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                thread_id TEXT,
                mode TEXT,
                tool_name TEXT NOT NULL,
                registry TEXT,
                arguments_json TEXT,
                result_summary TEXT,
                is_error INTEGER DEFAULT 0,
                duration_ms INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_thread ON audit_log(thread_id)")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore inizializzazione audit_log: {e}")


init_audit_db()


def log_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    thread_id: Optional[str] = None,
    mode: Optional[str] = None,
    registry: Optional[str] = None,
    result: Any = None,
    is_error: bool = False,
    duration_ms: Optional[int] = None,
) -> None:
    """Registra in modo persistente una chiamata a un tool. Mai bloccante."""
    try:
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, ensure_ascii=False, default=str)[:2000]
        else:
            result_str = str(result)[:2000] if result is not None else None

        conn = _get_conn()
        conn.execute(
            """INSERT INTO audit_log
               (timestamp, thread_id, mode, tool_name, registry, arguments_json, result_summary, is_error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                thread_id,
                mode,
                tool_name,
                registry,
                json.dumps(arguments, ensure_ascii=False, default=str),
                result_str,
                1 if is_error else 0,
                duration_ms,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Impossibile scrivere audit log: {e}")


def get_recent(limit: int = 100, thread_id: Optional[str] = None):
    """Restituisce le ultime N voci di audit (per endpoint diagnostico)."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        if thread_id:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE thread_id = ? ORDER BY id DESC LIMIT ?", (thread_id, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Impossibile leggere audit log: {e}")
        return []
