import json
import asyncio
from typing import Dict, Any, List
from tools import AVAILABLE_TOOLS, TOOL_SCHEMAS
from groq import Groq
import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYSTEM_AGENT_PROMPT = """You are Maya's Autonomous Task Execution Engine.
Your job is to solve the Boss's task step-by-step using your available tools.

CORE RULES:
1. THINK first: What information or file action do I need next?
2. ACT: Call the appropriate tool with precise arguments.
3. OBSERVE: Look at the tool output. If there is an error, analyze and fix it.
4. FINISH: Only when the objective is completely met, provide a comprehensive executive final response in Hindi/Hinglish.
5. Do NOT hallucinate search results or file operations. Always execute the tool.
"""

async def run_react_agent(task_description: str, max_turns: int = 6) -> str:
    """
    True ReAct Loop:
    Think -> Tool Call -> Execute Tool -> Observe Output -> Repeat until Done
    """
    if not groq_client:
        return "Error: Groq client not configured for agent execution."

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_AGENT_PROMPT},
        {"role": "user", "content": f"Boss Task: {task_description}"}
    ]

    print(f"[REACT ENGINE] Starting autonomous execution for: {task_description}")

    for turn in range(max_turns):
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto"
                )
            )

            msg = response.choices[0].message
            tool_calls = msg.tool_calls

            # Case 1: Agent has finished the task (No more tools needed)
            if not tool_calls:
                final_answer = msg.content or "Task completed successfully."
                print(f"[REACT ENGINE] Task finished at turn {turn + 1}")
                return final_answer

            # Case 2: Agent wants to run one or more tools
            # Assistant's thought/decision add karo
            messages.append(msg)

            for tc in tool_calls:
                fn_name = tc.function.name
                call_id = tc.id
                
                try:
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}

                print(f"[REACT ENGINE] Turn {turn + 1} -> Tool: '{fn_name}' with args: {fn_args}")

                # Real Tool Execution (Maya ke Haath)
                if fn_name in AVAILABLE_TOOLS:
                    try:
                        tool_func = AVAILABLE_TOOLS[fn_name]
                        observation = tool_func(**fn_args)
                    except Exception as e:
                        observation = f"Tool execution failed with error: {str(e)}"
                else:
                    observation = f"Error: Tool '{fn_name}' not recognized."

                # Send observation back to agent memory
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": str(observation)
                })

        except Exception as err:
            print(f"[REACT ENGINE ERROR]: {err}")
            return f"Boss, टास्क निष्पादन में तकनीकी समस्या आई: {str(err)}"

    return "Task reached maximum step limit. Partial execution saved."
