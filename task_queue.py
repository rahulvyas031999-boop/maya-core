import sqlite3
import json
import time
import os
from typing import List, Dict, Any, Optional

DB_FILE = os.getenv("DB_PATH", "maya_jobs.db")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Improves concurrent read/write safety under async FastAPI workers
    cursor.execute("PRAGMA journal_mode=WAL;")

    # 1. Persistent Autonomous Tasks Queue
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            prompt TEXT,
            status TEXT,
            modifications TEXT,
            result TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)

  
    # 2. Permanent Long-Term Memory (User Directives, Configs & Knowledge)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_memory (
            key TEXT PRIMARY KEY,
            value TEXT,
            category TEXT,
            updated_at REAL
        )
    """)

    conn.commit()
    conn.close()


init_db()


# --- Task Queue Engine ---
def create_task(task_id: str, prompt: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = time.time()
    cursor.execute("""
        INSERT INTO tasks (task_id, prompt, status, modifications, result, created_at, updated_at)
        VALUES (?, ?, 'pending', '[]', '', ?, ?)
    """, (task_id, prompt, now, now))
    conn.commit()
    conn.close()


def append_modification(task_id: str, mod_text: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT modifications FROM tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    mods = json.loads(row[0])
    mods.append(mod_text)
    cursor.execute("""
        UPDATE tasks SET modifications = ?, updated_at = ? WHERE task_id = ?
    """, (json.dumps(mods), time.time(), task_id))
    conn.commit()
    conn.close()
    return True


def get_latest_active_task_id() -> Optional[str]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT task_id FROM tasks
        WHERE status IN ('pending', 'processing')
        ORDER BY created_at DESC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    # FIX: params tuple was previously embedded inside the SQL string itself,
    # which produced a malformed query and raised sqlite3.OperationalError
    # every time this function was called.
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT task_id, prompt, status, modifications, result
        FROM tasks WHERE task_id = ?
    """, (task_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "task_id": row[0],
        "prompt": row[1],
        "status": row[2],
        "modifications": json.loads(row[3]),
        "result": row[4]
    }


def update_task_status(task_id: str, status: str, result: str = ""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE task_id = ?
    """, (status, result, time.time(), task_id))
    conn.commit()
    conn.close()


def get_active_tasks_summary() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT task_id, prompt, status FROM tasks
        WHERE status IN ('pending', 'processing')
        ORDER BY created_at ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{"task_id": r[0], "prompt": r[1], "status": r[2]} for r in rows]


def get_unprocessed_tasks() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT task_id, prompt FROM tasks
        WHERE status IN ('pending', 'processing')
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{"task_id": r[0], "prompt": r[1]} for r in rows]


# --- Long-Term Memory Engine ---
def remember_fact(key: str, value: Any, category: str = "general"):
    """बॉस की कोई भी जानकारी, निर्देश या कॉन्फिग हमेशा के लिए सेव करें"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    cursor.execute("""
        INSERT OR REPLACE INTO user_memory (key, value, category, updated_at)
        VALUES (?, ?, ?, ?)
    """, (key, val_str, category, time.time()))
    conn.commit()
    conn.close()


def recall_memory(category: Optional[str] = None) -> Dict[str, Any]:
    """Maya के सोचने और निर्णय लेने के लिए सेव की गई मेमोरी लोड करें"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if category:
        cursor.execute("SELECT key, value FROM user_memory WHERE category = ?", (category,))
    else:
        cursor.execute("SELECT key, value FROM user_memory")
    rows = cursor.fetchall()
    conn.close()
    memories = {}
    for k, v in rows:
        try:
            memories[k] = json.loads(v)
        except Exception:
            memories[k] = v
    return memories


# Auto-register hardware-verified models into permanent memory on boot
def lock_verified_models_to_memory():
    verified_stack = {
        "groq_chat_model": "openai/gpt-oss-20b",
        "groq_whisper_model": "whisper-large-v3-turbo",
        "gemini_fallback_model": "gemini-3.6-flash",
        "tts_voice": "hi-IN-SwaraNeural",
        "status": "production_verified"
    }
    remember_fact("active_model_registry", verified_stack, category="system_config")


lock_verified_models_to_memory()
