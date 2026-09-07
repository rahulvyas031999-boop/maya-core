import os
import io
import time
import json
import base64
import asyncio
import urllib.parse
import httpx
import edge_tts
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
                facts = json.load(f).get("facts", [])
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

def build_system_prompt() -> str:
    mem = load_memory()
    last_task = get_last_completed_task()
    return (
        "You are Maya, an ultra-intelligent, sovereign female AI Meta-Agent for 'Boss'. "
        "Converse in natural, sweet, crisp Hindi/Hinglish using strictly female grammatical inflections ('करती हूँ', 'बताती हूँ'). "
        "PRIMARY PROTOCOLS: "
        "1. Active Voice Link: Keep replies very crisp, punchy, and conversational (1-2 lines maximum for speaking). "
        "2. Never use robotic greetings repeatedly. Address Boss with high respect and energy. "
        f"\n[PERSISTENT MEMORY]\n{mem}\n"
        f"\n[BACKGROUND STATUS]\n{last_task}\n"
    )

# --- Free Edge-TTS Neural Voice Engine ---
async def generate_neural_speech(text: str) -> str:
    """Microsoft Azure Neural Voice - Free & Unlimited"""
    try:
        clean_text = text.replace("*", "").replace("#", "").replace("`", "")
        communicate = edge_tts.Communicate(clean_text, voice="hi-IN-SwaraNeural")
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])
        return base64.b64encode(audio_stream.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[EDGE-TTS ERROR]: {e}")
        return ""

# --- Autonomous Background Task Engine ---
async def execute_background_task(task_description: str):
    print(f"[ORCHESTRATOR] Background task started: {task_description}")
    generated_report = ""
    prompt = (
        f"You are Maya, an ultra-intelligent, professional AI Meta-Agent for Boss.\n"
        f"Assignment: {task_description}\n"
        f"Provide a comprehensive, high-value, deeply researched executive report in crisp, natural Hindi/Hinglish."
    )

    if gemini_client:
        try:
            res = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            if res and hasattr(res, "text") and res.text:
                generated_report = res.text
        except Exception as e:
            print(f"[ORCHESTRATOR] Gemini task error: {e}")

    if not generated_report and groq_client:
        try:
            loop = asyncio.get_running_loop()
            chat = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are Maya executing an autonomous report for Boss. Write in Hindi/Hinglish."},
                        {"role": "user", "content": task_description}
                    ],
                    model="openai/gpt-oss-20b"
                )
            )
            generated_report = chat.choices[0].message.content
        except Exception as e:
            print(f"[ORCHESTRATOR] Groq task error: {e}")

    if not generated_report:
        generated_report = "Boss, टास्क प्रोसेस करने में समस्या आई।"

    summary = generated_report[:150] + "..."
    record_completed_task(task_description, summary)

    chat_id = get_boss_chat_id()
    if chat_id and TELEGRAM_BOT_TOKEN:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        message_text = f"🚨 **TASK COMPLETED, BOSS!**\n\n🎯 **Task:** `{task_description}`\n\n📋 **Report:**\n\n{generated_report}"
        chunks = [message_text[i:i+3800] for i in range(0, len(message_text), 3800)] if len(message_text) > 4000 else [message_text]

        async with httpx.AsyncClient() as client:
            for ch in chunks:
                try:
                    await client.post(url, json={"chat_id": chat_id, "text": ch}, timeout=15.0)
                except Exception as err:
                    print(f"Telegram report delivery error: {err}")

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
        await update.message.reply_text("नमस्ते Boss! Maya Sovereign Link स्थापित हो चुका है।")

    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        save_boss_chat_id(str(chat_id))
        text = update.message.text.strip()
        lower_text = text.lower()

        # Image Handling
        image_triggers = ["image", "photo", "tasveer", "चित्र", "picture", "wallpaper"]
        action_triggers = ["banao", "generate", "create", "dikhao", "send"]
        if any(t in lower_text for t in image_triggers) and any(a in lower_text for a in action_triggers):
            await update.message.reply_text("Boss, इमेज रेंडर हो रही है, बस कुछ सेकंड...")
            clean_prompt = text
            for w in ["maya", "generate karo", "generate", "image", "photo", "banao", "ek", "ki"]:
                clean_prompt = clean_prompt.replace(w, "").replace(w.capitalize(), "")
            clean_prompt = clean_prompt.strip() or text
            img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_prompt)}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
            try:
                await update.message.reply_photo(photo=img_url, caption=f"✨ Boss, आपकी इमेज तैयार है!\n\n🎯 Prompt: {text}")
            except Exception:
                await update.message.reply_text(f"Boss, यह रहा आपका इमेज लिंक:\n{img_url}")
            return

        # Background Research Task
        if any(w in lower_text for w in ["background", "बैकग्राउंड", "रिसर्च करो", "research karo", "create website", "project"]):
            asyncio.create_task(execute_background_task(text))
            await update.message.reply_text("Boss, मैंने बैकग्राउंड में काम शुरू कर दिया है। रिपोर्ट तैयार होते ही इसी चैट में भेजती हूँ।")
            return

        # Normal Chat
        reply = ""
        if gemini_client:
            try:
                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=text,
                    config=types.GenerateContentConfig(system_instruction=build_system_prompt())
                )
                if response and hasattr(response, "text") and response.text:
                    reply = response.text
            except Exception:
                pass

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
                print(f"[GROQ ERROR]: {e}")

        if reply:
            await update.message.reply_text(reply)
        else:
            await update.message.reply_text("Boss, सर्वर व्यस्त है। कृपया पुनः प्रयास करें।")

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

# --- Real-Time Hybrid Voice Call Link ---
@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    print("[WEBSOCKET] Realtime Call Link Connected")

    # Initial Voice Greeting via Swara Neural
    welcome_text = "नमस्ते Boss! कॉल कनेक्ट हो चुकी है। कहिए, आज क्या प्लान है?"
    welcome_audio = await generate_neural_speech(welcome_text)
    if welcome_audio:
        await ws.send_json({"type": "audio", "data": welcome_audio})
        await ws.send_json({"type": "reply_text", "text": welcome_text})

    async def keep_alive():
        try:
            while True:
                await asyncio.sleep(15)
                await ws.send_json({"type": "ping", "timestamp": time.time()})
        except Exception:
            pass

    asyncio.create_task(keep_alive())

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            user_query = ""

            # 1. Audio Voice Input via Groq Whisper
            if msg_type == "audio_blob" and groq_client:
                try:
                    wav_bytes = base64.b64decode(msg.get("data", ""))
                    audio_file = io.BytesIO(wav_bytes)
                    audio_file.name = "audio.wav"
                    loop = asyncio.get_running_loop()
                    transcription = await loop.run_in_executor(
                        None,
                        lambda: groq_client.audio.transcriptions.create(
                            file=audio_file, model="whisper-large-v3", language="hi"
                        )
                    )
                    user_query = transcription.text.strip()
                except Exception as e:
                    print(f"[WHISPER ERROR]: {e}")

            elif msg_type == "query":
                user_query = msg.get("text", "").strip()

            if user_query:
                # Transcribed text UI par display karo
                await ws.send_json({"type": "transcript", "text": user_query})
                lower_q = user_query.lower()

                # Action Check 1: Image Generation
                if any(t in lower_q for t in ["image", "photo", "tasveer", "चित्र"]) and any(a in lower_q for a in ["banao", "generate", "dikhao", "create"]):
                    clean_p = user_query
                    for w in ["maya", "generate karo", "generate", "image", "photo", "banao", "ek", "ki"]:
                        clean_p = clean_p.replace(w, "").replace(w.capitalize(), "")
                    clean_p = clean_p.strip() or user_query
                    img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_p)}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                    await ws.send_json({"type": "image", "url": img_url})

                    # Telegram Sync
                    chat_id = get_boss_chat_id()
                    if chat_id and TELEGRAM_BOT_TOKEN:
                        async def sync_photo():
                            async with httpx.AsyncClient() as client:
                                try:
                                    await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", json={
                                        "chat_id": chat_id, "photo": img_url, "caption": f"✨ Boss, Live Call Image!\n🎯 {user_query}"
                                    }, timeout=15.0)
                                except Exception: pass
                        asyncio.create_task(sync_photo())

                    maya_reply = "Boss, स्क्रीन पर देखिए, इमेज तैयार कर दी है और टेलीग्राम पर भी भेज दी है।"
                
                # Action Check 2: Background Tasks
                elif any(w in lower_q for w in ["background", "रिसर्च करो", "project", "banao"]):
                    asyncio.create_task(execute_background_task(user_query))
                    maya_reply = "Boss, मैंने बैकग्राउंड में काम शुरू कर दिया है। पूरी रिपोर्ट टेलीग्राम पर भेज दूँगी।"

                # Action Check 3: General Intelligence via Gemini / Groq Text
                else:
                    maya_reply = ""
                    if gemini_client:
                        try:
                            res = gemini_client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=user_query,
                                config=types.GenerateContentConfig(system_instruction=build_system_prompt())
                            )
                            if res and hasattr(res, "text") and res.text:
                                maya_reply = res.text
                        except Exception:
                            pass

                    if not maya_reply and groq_client:
                        try:
                            loop = asyncio.get_running_loop()
                            completion = await loop.run_in_executor(
                                None,
                                lambda: groq_client.chat.completions.create(
                                    messages=[
                                        {"role": "system", "content": build_system_prompt()},
                                        {"role": "user", "content": user_query}
                                    ],
                                    model="openai/gpt-oss-20b"
                                )
                            )
                            maya_reply = completion.choices[0].message.content
                        except Exception as e:
                            print(f"[GROQ CHAT ERROR]: {e}")

                    if not maya_reply:
                        maya_reply = "जी Boss, बताइए मैं आपकी क्या सहायता कर सकती हूँ?"

                # UI Update & Neural Voice Stream
                await ws.send_json({"type": "reply_text", "text": maya_reply})
                audio_b64 = await generate_neural_speech(maya_reply)
                if audio_b64:
                    await ws.send_json({"type": "audio", "data": audio_b64})

    except WebSocketDisconnect:
        print("[WEBSOCKET] Live call disconnected")
    except Exception as e:
        print(f"[WEBSOCKET ERROR]: {e}")

@app.get("/", response_class=HTMLResponse)
async def home():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Maya Sovereign OS Online</h1>"
