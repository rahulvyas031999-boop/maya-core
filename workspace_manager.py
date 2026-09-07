import os
import mimetypes
from typing import List, Dict, Any

WORKSPACE_DIR = os.path.abspath("workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def get_workspace_path(relative_path: str) -> str:
    """Path traversal attack rokne ke liye sanitized safe path"""
    clean_path = os.path.normpath(os.path.join(WORKSPACE_DIR, relative_path.lstrip("/\\")))
    if not clean_path.startswith(WORKSPACE_DIR):
        raise ValueError("Access Denied: Path is outside workspace.")
    return clean_path

def list_artifacts() -> List[Dict[str, Any]]:
    """Workspace ke andar banni sabhi files ki list"""
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

def save_artifact(relative_path: str, content: str) -> str:
    """File ko safe directory me write karta hai"""
    target = get_workspace_path(relative_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return target
