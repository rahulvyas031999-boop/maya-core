import os
import io
import json
import asyncio
import urllib.parse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from google import genai
from google.genai import types

app = FastAPI(title="Maya Meta-Agent OS Live")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

MEMORY_FILE = "maya_memory.json"

def load_memory() -> str:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                facts = data.get("facts", [])
                if facts:
                    return "PAST MEMORY OF BOSS:\n" + "\n".join([f"- {item}" for item in facts[-10:]])
        except Exception:
            pass
    return "No prior memory recorded yet."

def save_memory_fact(fact: str):
    data = {"facts": []}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"facts": []}
    data.setdefault("facts", []).append(fact)
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Memory save error: {e}")

TOOL_DECLARATIONS = [
    {
        "name": "generate_image",
        "description": "Trigger this immediately when Boss asks for any photo, image, drawing, portrait, or visual. Construct a detailed 8k English prompt and call this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Highly detailed artistic visual English description for rendering"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "close_image",
        "description": "Trigger this immediately when Boss asks to close, hide, or remove the generated image from the screen.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "remember_fact",
        "description": "Store any personal detail, task, or instruction given by Boss into persistent memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The exact fact or preference to remember"
                }
            },
            "required": ["fact"]
        }
    }
]

def build_system_prompt() -> str:
    mem = load_memory()
    return (
        "You are Maya, a live conversational female Meta-Agent AI assistant for 'Boss'. "
        "Converse in completely natural, sweet, crisp Hindi/Hinglish using strictly female grammatical inflections ('करती हूँ', 'बताती हूँ'). "
        "CRITICAL RULES: "
        "1. Keep responses short, concise (1-2 lines), and instant. Never give long robotic speeches. "
        "2. When Boss asks for an image, trigger 'generate_image' immediately and say 'Boss, स्क्रीन पर देखिये'. "
        "3. When Boss asks to remove an image, trigger 'close_image' immediately. "
        "4. Always talk continuously like an active phone call companion. "
        f"\n[PERSISTENT MEMORY CONTEXT]\n{mem}\n"
    )

@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    if not gemini_client:
        await ws.send_json({"type": "error", "message": "Gemini API Key missing"})
        await ws.close()
        return

    sys_prompt = build_system_prompt()

    live_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text=sys_prompt)]),
        tools=[{"function_declarations": TOOL_DECLARATIONS}],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Despina"
                )
            )
        )
    )

    try:
        async with gemini_client.aio.live.connect(model="gemini-2.5-flash-native-audio-latest", config=live_config) as session:
            # Greet Boss instantly
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text="नमस्ते Maya! कॉल कनेक्ट हो चुकी है, छोटा सा स्वागत कीजिये।")])],
                turn_complete=True
            )

            async def keep_alive():
                try:
                    while True:
                        await asyncio.sleep(15)
                        await ws.send_json({"type": "ping"})
                except Exception:
                    pass

            async def receive_from_user():
                try:
                    while True:
                        data = await ws.receive_text()
                        msg = json.loads(data)
                        msg_type = msg.get("type")

                        if msg_type == "text_query":
                            query = msg.get("text", "").strip()
                            if query:
                                await session.send_client_content(
                                    turns=[types.Content(role="user", parts=[types.Part(text=query)])],
                                    turn_complete=True
                                )
                        elif msg_type == "pong":
                            pass
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as err:
                    print(f"Receive loop error: {err}")

            async def send_to_user():
                try:
                    while True:
                        async for response in session.receive():
                            server_content = response.server_content
                            if server_content and server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if hasattr(part, "inline_data") and part.inline_data:
                                        b64_audio = base64.b64encode(part.inline_data.data).decode("utf-8")
                                        await ws.send_json({"type": "audio", "data": b64_audio})

                            if response.tool_call:
                                fn_responses = []
                                for call in response.tool_call.function_calls:
                                    if call.name == "generate_image":
                                        prompt = call.args.get("prompt", "futuristic masterpiece 8k photorealistic")
                                        encoded = urllib.parse.quote(prompt)
                                        img_url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                                        await ws.send_json({"type": "image", "url": img_url, "prompt": prompt})
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={"result": "Image displayed on screen successfully."}
                                            )
                                        )
                                    elif call.name == "close_image":
                                        await ws.send_json({"type": "close_image"})
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={"result": "Image closed."}
                                            )
                                        )
                                    elif call.name == "remember_fact":
                                        fact = call.args.get("fact", "")
                                        if fact:
                                            save_memory_fact(fact)
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={"result": "Saved in memory."}
                                            )
                                        )

                                if fn_responses:
                                    try:
                                        await session.send_tool_response(function_responses=fn_responses)
                                    except Exception as err:
                                        print(f"Tool response error: {err}")
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as err:
                    print(f"Send loop error: {err}")

            await asyncio.gather(receive_from_user(), send_to_user(), keep_alive())

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        print(f"Live Session Error: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass

@app.get("/", response_class=HTMLResponse)
async def home():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Maya OS Live - templates/index.html not found</h1>"
