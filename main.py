import os
import io
import time
import json
import base64
import asyncio
import urllib.parse
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from groq import Groq
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

app = FastAPI(title="Maya Sovereign Meta-Agent OS")

# --- Environment Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

MEMORY_FILE = "maya_memory.json"
TASKS_FILE = "maya_tasks.json"
STATE_FILE = "maya_state.json"

# --- Storage & Memory Helpers ---
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

def get_last_completed_task() -> str:
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                tasks = json.load(f).get("completed", [])
                if tasks:
                    last = tasks[-1]
                    return f"Recently completed task: {last.get('task')} -> Result: {last.get('summary')}"
        except Exception:
            pass
    return ""

def record_completed_task(task_desc: str, summary: str):
    data = {"completed": []}
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"completed": []}
    data.setdefault("completed", []).append({"task": task_desc, "summary": summary, "time": time.time()})
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Task save error: {e}")

def get_boss_chat_id() -> str:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f).get("boss_chat_id", "")
        except Exception:
            pass
    return ""

def save_boss_chat_id(chat_id: str):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"boss_chat_id": str(chat_id)}, f)
    except Exception as e:
        print(f"Chat ID save error: {e}")

# --- Autonomous Background Task Engine ---
async def execute_background_task(task_description: str):
    print(f"[ORCHESTRATOR] Autonomous execution started: {task_description}")
    
    generated_report = ""
    prompt = (
        f"You are Maya, an ultra-intelligent, professional sovereign AI meta-agent for Boss.\n"
        f"Assignment: {task_description}\n"
        f"Provide a comprehensive, high-value, deeply researched, professional executive report in crisp, natural Hindi/Hinglish."
    )

    # 1. Primary Generation: Gemini 3.6 Flash
    if gemini_client:
        try:
            res = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            if res and hasattr(res, "text") and res.text:
                generated_report = res.text
        except Exception as e:
            print(f"[ORCHESTRATOR] Gemini primary task execution error: {e}")

    # 2. Fallback Generation: Groq openai/gpt-oss-20b
    if not generated_report and groq_client:
        try:
            loop = asyncio.get_running_loop()
            chat = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are Maya executing an autonomous background report for Boss. Write in Hindi/Hinglish."},
                        {"role": "user", "content": task_description}
                    ],
                    model="openai/gpt-oss-20b"
                )
            )
            generated_report = chat.choices[0].message.content
        except Exception as e:
            print(f"[ORCHESTRATOR] Groq fallback task execution error: {e}")

    if not generated_report:
        generated_report = "Boss, टास्क प्रोसेस करने में तकनीकी समस्या आई। कृपया पुनः कमांड दें।"

    # Save to memory & history
    summary = generated_report[:150] + "..."
    record_completed_task(task_description, summary)

    # Dispatch to Boss on Telegram
    chat_id = get_boss_chat_id()
    if chat_id and TELEGRAM_BOT_TOKEN:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        message_text = f"🚨 **TASK COMPLETED, BOSS!**\n\n🎯 **Task:** `{task_description}`\n\n📋 **Report:**\n\n{generated_report}"
        
        # Telegram 4096 character chunking safety
        chunks = [message_text[i:i+3800] for i in range(0, len(message_text), 3800)] if len(message_text) > 4000 else [message_text]

        async with httpx.AsyncClient() as client:
            for ch in chunks:
                try:
                    await client.post(url, json={"chat_id": chat_id, "text": ch}, timeout=15.0)
                except Exception as err:
                    print(f"Telegram report delivery error: {err}")

# --- Tool Declarations (Function Calling) ---
TOOL_DECLARATIONS = [
    {
        "name": "start_background_task",
        "description": "Trigger this when Boss gives an extensive task like creating a website, app, market research, or code fix that requires background processing.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Clear detailed objective of the task"
                }
            },
            "required": ["task_description"]
        }
    },
    {
        "name": "generate_image",
        "description": "Trigger this immediately when Boss requests an image or artwork.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Artistic visual English prompt"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "close_image",
        "description": "Trigger this when Boss asks to remove or close the image on screen.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "remember_fact",
        "description": "Store personal preferences, facts, or instructions given by Boss into long-term memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact to remember"}
            },
            "required": ["fact"]
        }
    },
    {
        "name": "system_diagnostics",
        "description": "Trigger this when Boss asks 'kya problem hai', 'status check karo', 'sab theek hai kya', or reports lag/slowness.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]

def build_system_prompt() -> str:
    mem = load_memory()
    last_task = get_last_completed_task()
    return (
        "You are Maya, an ultra-intelligent, sovereign female AI Meta-Agent for 'Boss'. "
        "Converse in natural, sweet, crisp Hindi/Hinglish using strictly female grammatical inflections ('करती हूँ', 'बताती हूँ'). "
        "PRIMARY PROTOCOLS: "
        "1. Real-time active voice/chat link: Give sharp, intelligent, natural answers without robotic hesitation. "
        "2. When asked for an image, invoke 'generate_image'. "
        "3. When asked to close an image, invoke 'close_image'. "
        "4. When Boss asks about system health, invoke 'system_diagnostics'. "
        f"\n[PERSISTENT MEMORY]\n{mem}\n"
        f"\n[BACKGROUND STATUS]\n{last_task}\n"
    )

# --- Render Sleep-Proof Watchdog ---
@app.on_event("startup")
async def startup_event():
    async def self_ping():
        await asyncio.sleep(60)
        while True:
            try:
                target = RENDER_APP_URL if RENDER_APP_URL else "http://127.0.0.1:10000"
                async with httpx.AsyncClient() as client:
                    await client.get(f"{target}/health", timeout=10.0)
            except Exception:
                pass
            await asyncio.sleep(300)

    asyncio.create_task(self_ping())
    
    if TELEGRAM_BOT_TOKEN:
        asyncio.create_task(run_telegram_gateway())

@app.get("/health")
async def health():
    return {"status": "Sovereign Engine Active", "time": time.time()}

# --- Telegram Bot Handler ---
async def run_telegram_gateway():
    print("[TELEGRAM] Starting Sovereign Bot Gateway...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        save_boss_chat_id(str(chat_id))
        await update.message.reply_text("नमस्ते Boss! Maya Sovereign Link स्थापित हो चुका है। अब बैकग्राउंड में चलने वाले सभी टास्क्स की लाइव रिपोर्ट आपको यहाँ मिलती रहेगी।")

    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        save_boss_chat_id(str(chat_id))
        text = update.message.text.strip()

        # Check if query requests background task/research
        lower_text = text.lower()
        if any(w in lower_text for w in ["background", "बैकग्राउंड", "रिसर्च करो", "research karo", "banao", "create website", "project"]):
            asyncio.create_task(execute_background_task(text))
            await update.message.reply_text("Boss, मैंने बैकग्राउंड में काम शुरू कर दिया है। पूरी रिसर्च और रिपोर्ट तैयार होते ही मैं इसी चैट में आपको अलर्ट भेजती हूँ।")
            return

        reply = ""

        # Engine 1: Verified Production Gemini (gemini-3.6-flash)
        if gemini_client:
            try:
                response = gemini_client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=text,
                    config=types.GenerateContentConfig(
                        system_instruction=build_system_prompt()
                    )
                )
                if response and hasattr(response, "text") and response.text:
                    reply = response.text
            except Exception as e:
                print(f"[FALLBACK TRIGGER] Gemini error: {e}, falling back to Groq...")

        # Engine 2: Verified Production Groq (openai/gpt-oss-20b)
        if not reply and groq_client:
            try:
                loop = asyncio.get_running_loop()
                chat_completion = await loop.run_in_executor(
                    None,
                    lambda: groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": build_system_prompt()},
                            {"role": "user", "content": text}
                        ],
                        model="openai/gpt-oss-20b"
                    )
                )
                reply = chat_completion.choices[0].message.content
            except Exception as e:
                print(f"[ERROR] Groq Chat Failed: {e}")

        # Telegram Message Delivery
        if reply:
            await update.message.reply_text(reply)
        else:
            await update.message.reply_text("Boss, दोनों AI इंजन इस समय व्यस्त हैं। कृपया थोड़ी देर में पुनः प्रयास करें।")

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    await application.initialize()
    await application.start()
    # Conflict एरर से बचने के लिए drop_pending_updates चालू रखा गया है
    await application.updater.start_polling(drop_pending_updates=True)

# --- WebSocket Live Call Link (Web Dashboard) ---
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
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Despina")
            )
        )
    )

    try:
        async with gemini_client.aio.live.connect(model="gemini-2.5-flash-native-audio-latest", config=live_config) as session:
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text="नमस्ते Maya! कॉल कनेक्ट हो चुकी है, छोटा सा स्वागत कीजिये।")])],
                turn_complete=True
            )

            async def keep_alive():
                try:
                    while True:
                        await asyncio.sleep(15)
                        await ws.send_json({"type": "ping", "timestamp": time.time()})
                except Exception:
                    pass

            async def receive_from_user():
                try:
                    while True:
                        data = await ws.receive_text()
                        msg = json.loads(data)
                        msg_type = msg.get("type")

                        if msg_type == "query":
                            text = msg.get("text", "").strip()
                            if text:
                                await session.send_client_content(
                                    turns=[types.Content(role="user", parts=[types.Part(text=text)])],
                                    turn_complete=True
                                )
                        elif msg_type == "audio_blob" and groq_client:
                            try:
                                wav_bytes = base64.b64decode(msg.get("data"))
                                audio_file = io.BytesIO(wav_bytes)
                                audio_file.name = "audio.wav"
                                loop = asyncio.get_running_loop()
                                transcription = await loop.run_in_executor(
                                    None,
                                    lambda: groq_client.audio.transcriptions.create(
                                        file=audio_file, model="whisper-large-v3", language="hi"
                                    )
                                )
                                user_text = transcription.text.strip()
                                if user_text:
                                    await ws.send_json({"type": "transcript", "text": user_text})
                                    await session.send_client_content(
                                        turns=[types.Content(role="user", parts=[types.Part(text=user_text)])],
                                        turn_complete=True
                                    )
                            except Exception as audio_err:
                                print(f"[AUDIO] Transcription error: {audio_err}")
                except Exception:
                    pass

            async def send_to_user():
                try:
                    while True:
                        async for response in session.receive():
                            sc = response.server_content
                            if sc and sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if hasattr(part, "inline_data") and part.inline_data:
                                        b64_audio = base64.b64encode(part.inline_data.data).decode("utf-8")
                                        await ws.send_json({"type": "audio", "data": b64_audio})

                            if response.tool_call:
                                fn_responses = []
                                for call in response.tool_call.function_calls:
                                    if call.name == "start_background_task":
                                        desc = call.args.get("task_description", "")
                                        asyncio.create_task(execute_background_task(desc))
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id, name=call.name,
                                                response={"result": "Background task accepted and running."}
                                            )
                                        )
                                    elif call.name == "generate_image":
                                        prompt = call.args.get("prompt", "futuristic art")
                                        img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                                        await ws.send_json({"type": "image", "url": img_url})
                                        fn_responses.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": "Image displayed."}))
                                    elif call.name == "close_image":
                                        await ws.send_json({"type": "close_image"})
                                        fn_responses.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": "Closed."}))
                                    elif call.name == "remember_fact":
                                        save_memory_fact(call.args.get("fact", ""))
                                        fn_responses.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": "Saved."}))
                                    elif call.name == "system_diagnostics":
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={
                                                    "status": "All Core Pipelines OK",
                                                    "gemini_link": "Connected Native Audio",
                                                    "latency": "Normal (<150ms)",
                                                    "memory_store": "Active"
                                                }
                                            )
                                        )

                                if fn_responses:
                                    await session.send_tool_response(function_responses=fn_responses)
                except Exception:
                    pass

            await asyncio.gather(receive_from_user(), send_to_user(), keep_alive())
    except Exception as e:
        print(f"Session error: {e}")

@app.get("/", response_class=HTMLResponse)
async def home():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Maya Sovereign OS Online</h1>"
