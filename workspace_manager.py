import os
import aiofiles
from typing import List, Dict, Any

WORKSPACE_DIR = os.path.abspath(os.getenv("WORKSPACE_PATH", "workspace"))
os.makedirs(WORKSPACE_DIR, exist_ok=True)


def get_workspace_path(relative_path: str) -> str:
    """Path traversal attack रोकने के लिए sanitized safe path"""
    clean_path = os.path.normpath(os.path.join(WORKSPACE_DIR, relative_path.lstrip("/\\")))

    # Sibling directory exploit prevention
    if not (clean_path == WORKSPACE_DIR or clean_path.startswith(WORKSPACE_DIR + os.sep)):
        raise ValueError("Access Denied: Path is outside workspace.")

    return clean_path


def list_artifacts() -> List[Dict[str, Any]]:
    """Workspace के अंदर बनी सभी फाइल्स की लिस्ट (Fast Sync stat)"""
    files_list = []
    for root, _, files in os.walk(WORKSPACE_DIR):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, WORKSPACE_DIR)
            size_kb = round(os.path.getsize(full_path) / 1024, 2)
            files_list.append({
                "filename": f,
                "relative_path": rel_path.replace("\\", "/"),
                "size_kb": size_kb
            })
    return files_list


async def save_artifact(relative_path: str, content: str) -> str:
    """फ़ाइल को सुरक्षित डायरेक्टरी में असिंक्रोनस तरीके से लिखता है (Non-Blocking)"""
    target = get_workspace_path(relative_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    
    # Event-loop safe file writing
    async with aiofiles.open(target, "w", encoding="utf-8") as f:
        await f.write(content)
        
    return target
