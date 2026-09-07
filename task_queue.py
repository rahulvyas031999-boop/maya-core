import sqlite3
import time
import json
from typing import Dict, Any, List, Optional

DB_FILE = "maya_jobs.db"

def init_db():
    """डेटाबेस और टास्क टेबल को सुरक्षित तरीके से इनिशियलाइज़ करता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                modifications TEXT DEFAULT '[]',
                status TEXT DEFAULT 'pending',
                created_at REAL,
                completed_at REAL,
                result TEXT DEFAULT ''
            )
        """)
        conn.commit()

# ऐप लोड होते ही DB टेबल तैयार
init_db()

def create_task(task_id: str, prompt: str) -> None:
    """नया टास्क डिस्क पर सुरक्षित रूप से जोड़ता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO jobs (task_id, prompt, modifications, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
        """, (task_id, prompt, json.dumps([]), time.time()))
        conn.commit()

def append_modification(task_id: str, modification_text: str) -> bool:
    """चल रहे टास्क में लाइव कॉल के दौरान नया बदलाव जोड़ता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT modifications FROM jobs WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            mods = json.loads(row[0] or "[]")
            mods.append(modification_text)
            cursor.execute("""
                UPDATE jobs SET modifications = ? WHERE task_id = ?
            """, (json.dumps(mods), task_id))
            conn.commit()
            return True
    return False

def get_latest_active_task_id() -> Optional[str]:
    """सबसे हालिया रनिंग या पेंडिंग टास्क की ID निकालता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT task_id FROM jobs 
            WHERE status IN ('pending', 'processing') 
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cursor.fetchone()
        return row[0] if row else None

def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """टास्क का पूरा स्टेटस और डेटा फेच करता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT task_id, prompt, modifications, status, result FROM jobs WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            return {
                "task_id": row[0],
                "prompt": row[1],
                "modifications": json.loads(row[2] or "[]"),
                "status": row[3],
                "result": row[4]
            }
    return None

def update_task_status(task_id: str, status: str, result: str = "") -> None:
    """टास्क स्टेटस को 'processing' या 'completed' में अपडेट करता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET status = ?, result = ?, completed_at = ? 
            WHERE task_id = ?
        """, (status, result, time.time() if status == 'completed' else None, task_id))
        conn.commit()

def get_active_tasks_summary() -> List[Dict[str, str]]:
    """मास्टर राउटर के लिए सभी एक्टिव टास्क्स की लिस्ट देता है"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT task_id, prompt FROM jobs 
            WHERE status IN ('pending', 'processing')
        """)
        return [{"id": r[0], "task": r[1]} for r in cursor.fetchall()]

def get_unprocessed_tasks() -> List[Dict[str, Any]]:
    """सर्वर रीस्टार्ट होने पर पेंडिंग टास्क्स को ऑटो-रिकवर करने के लिए"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT task_id, prompt, modifications FROM jobs 
            WHERE status IN ('pending', 'processing')
        """)
        rows = cursor.fetchall()
        return [{
            "task_id": r[0],
            "prompt": r[1],
            "modifications": json.loads(r[2] or "[]")
        } for r in rows]
