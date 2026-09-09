import os
import sys
import asyncio
import aiofiles
from duckduckgo_search import AsyncDDGS
from workspace_manager import get_workspace_path

async def tool_web_search(query: str, max_results: int = 5) -> str:
    """लाइव इंटरनेट पर सर्च करके ताज़ा डेटा लाता है (Non-blocking)"""
    try:
        async with AsyncDDGS() as ddgs:
            results = await ddgs.text(query, max_results=max_results)
            if not results:
                return "No search results found."
            formatted = []
            for r in results:
                formatted.append(f"Title: {r.get('title')}\nSnippet: {r.get('body')}\nURL: {r.get('href')}\n")
            return "\n---\n".join(formatted)
    except Exception as e:
        return f"Web search failed: {str(e)}"

async def tool_write_file(filepath: str, content: str) -> str:
    """सुरक्षित workspace डायरेक्टरी में असल फ़ाइल लिखता है (Asynchronous)"""
    try:
        safe_path = get_workspace_path(filepath)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        async with aiofiles.open(safe_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return f"File '{filepath}' saved successfully in workspace ({len(content)} chars)."
    except Exception as e:
        return f"Failed to write file '{filepath}': {str(e)}"

async def tool_read_file(filepath: str) -> str:
    """Workspace के अंदर से फ़ाइल का वास्तविक कंटेंट पढ़ता है (Asynchronous)"""
    try:
        safe_path = get_workspace_path(filepath)
        if not os.path.exists(safe_path):
            return f"Error: File '{filepath}' does not exist in workspace."
        async with aiofiles.open(safe_path, "r", encoding="utf-8") as f:
            return await f.read()
    except Exception as e:
        return f"Failed to read file '{filepath}': {str(e)}"

async def tool_execute_python(code: str) -> str:
    """Sandboxed Python execution with Strict Environment & Async Subprocess"""
    try:
        safe_cwd = get_workspace_path(".")
        os.makedirs(safe_cwd, exist_ok=True)

        # SECURITY: Strip sensitive API keys before running LLM generated code
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "PYTHONUNBUFFERED": "1"
        }

        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            cwd=safe_cwd,
            env=safe_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return "Error: Execution timed out after 15 seconds."

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        output = f"Exit Code: {process.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

        # Guard against blowing up the LLM's token budget
        if len(output) > 4000:
            output = output[:4000] + "\n...[truncated]"

        return output

    except Exception as e:
        return f"Execution failed: {str(e)}"

AVAILABLE_TOOLS = {
    "web_search": tool_web_search,
    "write_file": tool_write_file,
    "read_file": tool_read_file,
    "execute_python": tool_execute_python,
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
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute a snippet of Python code in a sandboxed subprocess (15s timeout). Returns stdout, stderr, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source code to execute"}
                },
                "required": ["code"]
            }
        }
    }
        ]
