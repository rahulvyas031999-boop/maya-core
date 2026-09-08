import json
import asyncio
import os
from typing import Dict, Any, List
from tools import AVAILABLE_TOOLS, TOOL_SCHEMAS
from groq import Groq
from google import genai

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

PRIMARY_GROQ_MODEL = "openai/gpt-oss-20b"
FALLBACK_GEMINI_MODEL = "gemini-3.6-flash"

SYSTEM_AGENT_PROMPT = """You are Maya's Autonomous Execution Engine.
Your job is to complete the Boss's task step-by-step using available tools.
Strictly speak as a female agent in Hindi/Hinglish (ALWAYS use 'करती हूँ', 'बताती हूँ').

PROTOCOL:
1. THINK: Decide next logical step.
2. ACT: Call web_search, write_file, read_file, or execute_python.
3. OBSERVE & SELF-CORRECT: If execution shows an error, inspect output, fix code and re-test.
4. FINISH: Deliver crisp executive summary once verified.
"""


class MockMessage:
    """Used to normalize the Gemini fallback response into the same shape
    as a Groq ChatCompletionMessage, so run_react_agent can treat both
    providers identically."""
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


async def call_llm_safe(messages: List[Dict[str, Any]]) -> Any:
    # 1. Primary: Verified Groq openai/gpt-oss-20b (full tool-calling support)
    if groq_client:
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    model=PRIMARY_GROQ_MODEL,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    max_tokens=600
                )
            )
            return response.choices[0].message
        except Exception as e:
            print(f"[REACT GROQ WARNING]: {e}. Switching to Gemini {FALLBACK_GEMINI_MODEL}...")

    # 2. Hard Fallback: Google Gemini 3.6 Flash
    # NOTE: This fallback path does NOT execute tools. It is a text-only
    # safety net so the Boss still gets a coherent answer if Groq is down,
    # rather than a silent crash - but multi-step tasks that genuinely
    # require tool use (search/file/code) will not be completed by this
    # path. We tell the model that explicitly so it doesn't pretend to have
    # used a tool it doesn't have.
    if gemini_client:
        try:
            prompt_text = "\n".join([f"{m['role']}: {m.get('content', '')}" for m in messages])
            prompt_text += (
                "\n\n[SYSTEM NOTE: You are running in fallback mode with NO tool access. "
                "Do not claim to have searched, written files, or executed code. "
                "Answer directly in Hindi/Hinglish with female grammar, and if the task "
                "genuinely requires a tool, tell the Boss it needs to be retried once the "
                "primary engine is back online.]"
            )
            res = await asyncio.to_thread(
                lambda: gemini_client.models.generate_content(
                    model=FALLBACK_GEMINI_MODEL,
                    contents=prompt_text
                )
            )
            return MockMessage(content=res.text, tool_calls=None)
        except Exception as ge:
            print(f"[REACT GEMINI FALLBACK ERROR]: {ge}")

    return None


async def run_react_agent(task_description: str, max_turns: int = 5) -> str:
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_AGENT_PROMPT},
        {"role": "user", "content": f"Boss Task: {task_description}"}
    ]

    print(f"[REACT ENGINE] Running on verified {PRIMARY_GROQ_MODEL} (Fallback: {FALLBACK_GEMINI_MODEL}): {task_description}")

    for turn in range(max_turns):
        msg = await call_llm_safe(messages)
        if not msg:
            return "Boss, मॉडल्स पर अस्थायी लोड के कारण रिस्पॉन्स नहीं मिला।"

        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            final_ans = getattr(msg, "content", None) or "Task completed."
            print(f"[REACT ENGINE] Finished at turn {turn + 1}")
            return final_ans

        messages.append(msg)

        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except Exception:
                fn_args = {}

            print(f"[REACT ENGINE] Turn {turn + 1} -> Calling Tool: '{fn_name}'")

            if fn_name in AVAILABLE_TOOLS:
                try:
                    observation = AVAILABLE_TOOLS[fn_name](**fn_args)
                except Exception as e:
                    observation = f"Tool Execution Failed: {str(e)}"
            else:
                observation = f"Error: Tool '{fn_name}' not available."

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": fn_name,
                "content": str(observation)
            })

    # FIX: previously returned "Task completed. Workspace files updated."
    # here unconditionally, even though reaching this point means the loop
    # was cut off by max_turns WITHOUT the model ever giving a final
    # (non-tool-call) answer. That was a misleading success message for an
    # incomplete task. Report it honestly instead.
    return (
        "Boss, task ज़्यादा complex निकला और तय turns में पूरा नहीं हो पाया। "
        "कृपया task को छोटे हिस्सों में तोड़कर दोबारा भेजें।"
    )
