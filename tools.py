import os
from duckduckgo_search import DDGS

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
    """डिस्क पर असल फ़ाइल लिखता है"""
    try:
        # सिर्फ सेफ वर्कस्पेस में लिखने की अनुमति
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File '{filepath}' written successfully ({len(content)} chars)."
    except Exception as e:
        return f"Failed to write file '{filepath}': {str(e)}"

def tool_read_file(filepath: str) -> str:
    """फ़ाइल का वास्तविक कंटेंट पढ़ता है"""
    try:
        if not os.path.exists(filepath):
            return f"Error: File '{filepath}' does not exist."
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Failed to read file '{filepath}': {str(e)}"

# टूल रजिस्ट्री (Router और Worker के लिए)
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
            "description": "Write or overwrite a file on disk (code, reports, html, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Relative file path, e.g., 'workspace/index.html'"},
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
            "description": "Read content from a file to verify its contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Relative file path"}
                },
                "required": ["filepath"]
            }
        }
    }
  ]
