import sqlite3
import json
import time
import os
from typing import List, Dict, Any, Optional

DB_FILE = os.getenv("DB_PATH", "maya_jobs.db")

def _get_conn():
    """
    Centralized DB Connection:
    - check_same_thread=False: Allows FastAPI background tasks to share the connection pool.
    - timeout=15.0: Prevents 'database is locked' errors during heavy concurrent reads/writes.
    """
    conn = sqlite3.connect(DB_FILE, timeout=15.0, check_same_thread=False)
    # Ensures WAL is always active for concurrent access
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = _get_conn()
    cursor = conn.cursor()

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


# --- Task Queue Engine ---
def create_task(task_id: str, prompt: str):
    conn = _get_conn()
    cursor = conn.cursor()
    now = time.time()
    try:
        cursor.execute("""
            INSERT INTO tasks (task_id, prompt, status, modifications, result, created_at, updated_at)
            VALUES (?, ?, 'pending', '[]', '', ?, ?)
        """, (task_id, prompt, now, now))
        conn.commit()
    finally:
        conn.close()


def append_modification(task_id: str, mod_text: str) -> bool:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT modifications FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return False
        mods = json.loads(row[0])
        mods.append(mod_text)
        cursor.execute("""
            UPDATE tasks SET modifications = ?, updated_at = ? WHERE task_id = ?
        """, (json.dumps(mods), time.time(), task_id))
        conn.commit()
        return True
    finally:
        conn.close()


def get_latest_active_task_id() -> Optional[str]:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT task_id FROM tasks
            WHERE status IN ('pending', 'processing')
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT task_id, prompt, status, modifications, result
            FROM tasks WHERE task_id = ?
        """, (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "task_id": row[0],
            "prompt": row[1],
            "status": row[2],
            "modifications": json.loads(row[3]),
            "result": row[4]
        }
    finally:
        conn.close()


def update_task_status(task_id: str, status: str, result: str = ""):
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE task_id = ?
        """, (status, result, time.time(), task_id))
        conn.commit()
    finally:
        conn.close()


def get_active_tasks_summary() -> List[Dict[str, Any]]:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT task_id, prompt, status FROM tasks
            WHERE status IN ('pending', 'processing')
            ORDER BY created_at ASC
        """)
        rows = cursor.fetchall()
        return [{"task_id": r[0], "prompt": r[1], "status": r[2]} for r in rows]
    finally:
        conn.close()


def get_unprocessed_tasks() -> List[Dict[str, Any]]:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT task_id, prompt FROM tasks
            WHERE status IN ('pending', 'processing')
        """)
        rows = cursor.fetchall()
        return [{"task_id": r[0], "prompt": r[1]} for r in rows]
    finally:
        conn.close()


# --- Long-Term Memory Engine ---
def remember_fact(key: str, value: Any, category: str = "general"):
    """बॉस की कोई भी जानकारी, निर्देश या कॉन्फिग हमेशा के लिए सेव करें"""
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        cursor.execute("""
            INSERT OR REPLACE INTO user_memory (key, value, category, updated_at)
            VALUES (?, ?, ?, ?)
        """, (key, val_str, category, time.time()))
        conn.commit()
    finally:
        conn.close()


def recall_memory(category: Optional[str] = None) -> Dict[str, Any]:
    """Maya के सोचने और निर्णय लेने के लिए सेव की गई मेमोरी लोड करें"""
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        if category:
            cursor.execute("SELECT key, value FROM user_memory WHERE category = ?", (category,))
        else:
            cursor.execute("SELECT key, value FROM user_memory")
        rows = cursor.fetchall()
        memories = {}
        for k, v in rows:
            try:
                memories[k] = json.loads(v)
            except Exception:
                memories[k] = v
        return memories
    finally:
        conn.close()


def lock_verified_models_to_memory():
    verified_stack = {
        "groq_chat_model": "openai/gpt-oss-20b",
        "groq_whisper_model": "whisper-large-v3-turbo",
        "gemini_fallback_model": "gemini-3.6-flash",
        "tts_voice": "hi-IN-SwaraNeural",
        "status": "production_verified"
    }
    remember_fact("active_model_registry", verified_stack, category="system_config")


# -------------------------------------------------------------------
# सुरक्षित स्टार्टअप: जब फ़ाइल इंपोर्ट हो तभी डेटाबेस इनिशियलाइज़ करें
# -------------------------------------------------------------------
try:
    init_db()
    lock_verified_models_to_memory()
except Exception as e:
    print(f"[DB INIT ERROR] Failed to initialize database: {e}")
