import os
import re
import time
import json
import sqlite3
import logging
from typing import Optional, List, Dict, Any
import config

logger = logging.getLogger("thread_store")

def _get_conn():
    return sqlite3.connect(config.CHECKPOINT_DB_PATH)

def init_db():
    """Inizializza la tabella thread_messages nel database SQLite dei checkpoint."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thread_messages (
                thread_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                mode TEXT,
                tool_used TEXT,
                reasoning TEXT,
                plan_steps_json TEXT,
                plan_structure_json TEXT,
                execution_trace_json TEXT,
                rollback_trace_json TEXT,
                is_error INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, message_id)
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore inizializzazione thread_store SQLite: {e}")

# Inizializza al caricamento del modulo
init_db()

def save_turn(thread_id: str, user_input: str, response_data: Dict[str, Any]):
    """
    Salva atomicamente in SQLite sia il messaggio utente che la risposta assistente.
    """
    if not thread_id:
        return

    init_db()
    conn = _get_conn()
    cursor = conn.cursor()

    now_time = time.time()
    time_str = time.strftime("%H:%M", time.localtime(now_time))
    user_msg_id = f"user_{int(now_time * 1000)}"
    ast_msg_id = f"ast_{int(now_time * 1000) + 1}"

    try:
        # 1. Salva messaggio User
        cursor.execute("""
            INSERT OR REPLACE INTO thread_messages
            (thread_id, message_id, sender, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (thread_id, user_msg_id, "user", user_input, time_str))

        # 2. Prepara dati risposta Assistant
        resp_text = response_data.get("response") or ""
        if isinstance(resp_text, str):
            resp_text = re.sub(r'\[Mode:\s*[A-Za-z]+\]\n?', '', resp_text, flags=re.IGNORECASE).strip()
        else:
            resp_text = str(resp_text)
        mode = response_data.get("mode")
        tool_used = response_data.get("tool_used")
        
        plan_steps = response_data.get("plan_steps")
        plan_steps_json = json.dumps(plan_steps, ensure_ascii=False) if plan_steps else None

        plan_structure = response_data.get("plan_structure")
        plan_structure_json = json.dumps(plan_structure, ensure_ascii=False) if plan_structure else None

        execution_trace = response_data.get("execution_trace")
        execution_trace_json = json.dumps(execution_trace, ensure_ascii=False) if execution_trace else None

        rollback_trace = response_data.get("rollback_trace")
        rollback_trace_json = json.dumps(rollback_trace, ensure_ascii=False) if rollback_trace else None

        # Estrazione reasoning dallo trace se non esplicito
        reasoning = None
        if execution_trace and isinstance(execution_trace, list):
            for tr in execution_trace:
                if isinstance(tr, dict) and tr.get("reasoning"):
                    reasoning = tr.get("reasoning")
                    break

        is_error = 1 if response_data.get("error") else 0

        # 3. Salva messaggio Assistant
        cursor.execute("""
            INSERT OR REPLACE INTO thread_messages
            (thread_id, message_id, sender, content, timestamp, mode, tool_used, reasoning,
             plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json, is_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            thread_id,
            ast_msg_id,
            "assistant",
            resp_text,
            time_str,
            mode,
            tool_used,
            reasoning,
            plan_steps_json,
            plan_structure_json,
            execution_trace_json,
            rollback_trace_json,
            is_error
        ))

        conn.commit()
    except Exception as e:
        logger.error(f"Errore salvataggio turno thread '{thread_id}' in SQLite: {e}")
    finally:
        conn.close()


def get_thread_messages(thread_id: str) -> List[Dict[str, Any]]:
    """
    Recupera la cronologia messaggi tipata e strutturata per un thread.
    """
    if not thread_id:
        return []

    init_db()
    conn = _get_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT message_id, sender, content, timestamp, mode, tool_used, reasoning,
                   plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json, is_error
            FROM thread_messages
            WHERE thread_id = ?
            ORDER BY rowid ASC
        """, (thread_id,))
        rows = cursor.fetchall()
        conn.close()

        messages = []
        for row in rows:
            m_id, sender, content, ts, mode, tool_used, reasoning, ps_json, pst_json, et_json, rt_json, is_err = row
            
            msg_obj = {
                "id": m_id,
                "sender": sender,
                "content": content,
                "timestamp": ts,
                "mode": mode,
                "tool_used": tool_used,
                "reasoning": reasoning,
                "plan_steps": json.loads(ps_json) if ps_json else None,
                "plan_structure": json.loads(pst_json) if pst_json else None,
                "execution_trace": json.loads(et_json) if et_json else None,
                "rollback_trace": json.loads(rt_json) if rt_json else None,
                "isError": bool(is_err)
            }
            messages.append(msg_obj)

        return messages
    except Exception as e:
        logger.error(f"Errore lettura messaggi thread '{thread_id}': {e}")
        return []


def get_last_message(thread_id: str) -> Optional[str]:
    """Recupera l'anteprima del testo dell'ultimo messaggio di un thread."""
    if not thread_id:
        return None

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT content FROM thread_messages
            WHERE thread_id = ?
            ORDER BY rowid DESC LIMIT 1
        """, (thread_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def delete_thread_messages(thread_id: str):
    """Elimina tutti i messaggi associati a un thread."""
    if not thread_id:
        return
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore eliminazione messaggi thread '{thread_id}': {e}")


def clear_all_thread_messages():
    """Svuota l'intera tabella dei messaggi."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM thread_messages")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore azzeramento tabella thread_messages: {e}")
