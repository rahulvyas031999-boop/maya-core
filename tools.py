import os
from duckduckgo_search import DDGS
from workspace_manager import get_workspace_path

def tool_web_search(query: str, max_results: int = 5) -> str:
    """लाइव इंटरनेट पर सर्च करके ताज़ा डेटा लाता है"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No search results found."
            formatted = []
            for r in results:
                formatted.append(f"Title: {r.get('title')}\nSnippet: {r.get('body')}\nURL: {r.get('href')}\n")
            return "\n---\n".join(formatted)
    except Exception as e:
        return f"Web search failed: {str(e)}"

def tool_write_file(filepath: str, content: str) -> str:
    """सुरक्षित workspace डायरेक्टरी में असल फ़ाइल लिखता है"""
    try:
        safe_path = get_workspace_path(filepath)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File '{filepath}' saved successfully in workspace ({len(content)} chars)."
    except Exception as e:
        return f"Failed to write file '{filepath}': {str(e)}"

def tool_read_file(filepath: str) -> str:
    """Workspace के अंदर से फ़ाइल का वास्तविक कंटेंट पढ़ता है"""
    try:
        safe_path = get_workspace_path(filepath)
        if not os.path.exists(safe_path):
            return f"Error: File '{filepath}' does not exist in workspace."
        with open(safe_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Failed to read file '{filepath}': {str(e)}"

AVAILABLE_TOOLS = {
    "web_search": tool_web_search,
    "write_file": tool_write_file,
    "read_file": tool_read_file
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live internet for current information, facts, news, and technical solutions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file in workspace (e.g., 'index.html', 'report.md', 'script.py')",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Filename or relative path inside workspace"},
                    "content": {"type": "string", "description": "Full file content to write"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read content from an existing file in workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Filename or relative path inside workspace"}
                },
                "required": ["filepath"]
            }
        }
    }
]
