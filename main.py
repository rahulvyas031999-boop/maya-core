import os
import io
import re
import time
import json
import base64
import asyncio
import urllib.parse
import httpx
import edge_tts
from typing import Dict, Any, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from groq import Groq
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

app = FastAPI(title="Maya Sovereign Meta-Agent OS")

# --- Environment Setup ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

STATE_FILE = "maya_state.json"
TASKS_FILE = "maya_tasks.json"

# Active live WebSockets tracking for cross-alerts
ACTIVE_WEBSOCKETS: List[WebSocket] = []

# --- Persistent State Helpers ---
def load_json(filepath: str, default: Any) -> Any:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(filepath: str, data: Any):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[STORAGE ERROR]: {e}")

def get_boss_chat_id() -> str:
    return load_json(STATE_FILE, {}).get("boss_chat_id", "")

def save_boss_chat_id(chat_id: str):
    data = load_json(STATE_FILE, {})
    data["boss_chat_id"] = str(chat_id)
    save_json(STATE_FILE, data)

# --- Cross-Platform Unified Dispatcher ---
async def dispatch_to_telegram(text: str = None, photo_url: str = None, caption: str = ""):
    chat_id = get_boss_chat_id()
    if not chat_id or not TELEGRAM_BOT_TOKEN:
        return
    async with httpx.AsyncClient() as client:
        try:
            if photo_url:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    json={"chat_id": chat_id, "photo": photo_url, "caption": caption or "✨ Visual Delivery"},
                    timeout=15.0
                )
            if text:
                chunks = [text[i:i+3800] for i in range(0, len(text), 3800)] if len(text) > 4000 else [text]
                for ch in chunks:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": chat_id, "text": ch},
                        timeout=15.0
                    )
        except Exception as e:
            print(f"[TELEGRAM DISPATCH ERROR]: {e}")

# --- Autonomous Worker Engine with Dynamic Modification Support ---
async def run_autonomous_worker(task_id: str, initial_prompt: str):
    print(f"[AUTONOMOUS WORKER] Task {task_id} launched: {initial_prompt}")
    tasks_data = load_json(TASKS_FILE, {"active": {}, "completed": []})
    tasks_data["active"][task_id] = {
        "prompt": initial_prompt,
        "modifications": [],
        "created_at": time.time(),
        "status": "processing"
    }
    save_json(TASKS_FILE, tasks_data)

    # Allow time for mid-conversation user modifications to queue
    await asyncio.sleep(5)

    # Reload fresh specifications including changes added by user mid-call
    current_tasks = load_json(TASKS_FILE, {"active": {}, "completed": []})
    task_info = current_tasks.get("active", {}).get(task_id, {})
    mods = task_info.get("modifications", [])
    
    full_spec = initial_prompt
    if mods:
        full_spec += "\n\n[USER MODIFICATIONS APPLIED MID-CALL]:\n" + "\n".join([f"- {m}" for m in mods])

    deep_prompt = (
        f"You are Maya Sovereign Autonomous Worker.\n"
        f"Goal: Execute complete, production-level, exhaustive delivery for:\n{full_spec}\n\n"
        "Provide full code, architecture, steps, or exhaustive documentation in professional Hindi/Hinglish."
    )

    final_delivery = ""
    if gemini_client:
        try:
            res = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=deep_prompt
            )
            if res and hasattr(res, "text") and res.text:
                final_delivery = res.text
        except Exception:
            pass

    if not final_delivery and groq_client:
        try:
            loop = asyncio.get_running_loop()
            chat = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are Maya Autonomous Worker. Deliver deep, production-grade output."},
                        {"role": "user", "content": deep_prompt}
                    ],
                    model="openai/gpt-oss-20b"
                )
            )
            final_delivery = chat.choices[0].message.content
        except Exception as e:
            print(f"[WORKER LLM ERROR]: {e}")

    if not final_delivery:
        final_delivery = "Boss, टास्क प्रोसेस करने में त्रुटि आई। कृपया पुनः कमांड दें।"

    # Mark completed
    current_tasks = load_json(TASKS_FILE, {"active": {}, "completed": []})
    if task_id in current_tasks.get("active", {}):
        del current_tasks["active"][task_id]
    current_tasks.setdefault("completed", []).append({
        "task_id": task_id,
        "prompt": initial_prompt,
        "result_preview": final_delivery[:150],
        "time": time.time()
    })
    save_json(TASKS_FILE, current_tasks)

    # 1. Deliver full result to Telegram
    report_msg = f"🚀 **AUTONOMOUS TASK DEPLOYED, BOSS!**\n\n📌 **Task:** `{initial_prompt}`\n\n{final_delivery}"
    await dispatch_to_telegram(text=report_msg)

    # 2. Push alert to active live web call if connected
    for ws in ACTIVE_WEBSOCKETS:
        try:
            await ws.send_json({
                "type": "reply_text",
                "text": f"Boss, बैकग्राउंड टास्क '{initial_prompt[:30]}...' पूरा हो चुका है। मैंने पूरी रिपोर्ट टेलीग्राम पर भेज दी है।"
            })
        except Exception:
            pass

# --- Master Brain: Real-Time Intent & Context Classifier ---
def extract_clean_json(text: str) -> Dict[str, Any]:
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception:
        return {}

async def master_router(user_input: str) -> Dict[str, Any]:
    tasks_data = load_json(TASKS_FILE, {"active": {}, "completed": []})
    active_jobs = tasks_data.get("active", {})
    active_summary = [{"id": k, "task": v.get("prompt")} for k, v in active_jobs.items()]

    router_prompt = (
        f"You are the executive Master Brain of Maya Sovereign OS.\n"
        f"ACTIVE BACKGROUND TASKS: {json.dumps(active_summary, ensure_ascii=False)}\n"
        f"BOSS INPUT: \"{user_input}\"\n\n"
        "Analyze intent and return STRICT JSON with NO markdown:\n"
        "{\n"
        "  \"intent\": \"chat\" | \"new_heavy_task\" | \"modify_task\" | \"generate_image\",\n"
        "  \"voice_response\": \"Strictly 1 natural, crisp sentence in Hindi/Hinglish to speak to Boss\",\n"
        "  \"task_id\": \"id of active task if modify_task else empty\",\n"
        "  \"task_payload\": \"full clean spec or image prompt\",\n"
        "  \"screen_content\": \"structured text/code for HUD viewer or empty\"\n"
        "}"
    )

    decision = {}
    if groq_client:
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are Maya Master Router. Output valid JSON only."},
                        {"role": "user", "content": router_prompt}
                    ],
                    model="openai/gpt-oss-20b",
                    response_format={"type": "json_object"}
                )
            )
            decision = extract_clean_json(res.choices[0].message.content)
        except Exception:
            pass

    if not decision and gemini_client:
        try:
            res = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=router_prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            decision = extract_clean_json(res.text)
        except Exception:
            pass

    return decision or {
        "intent": "chat",
        "voice_response": "जी Boss, बताइए आगे क्या करना है?",
        "task_payload": user_input,
        "screen_content": ""
    }

async def generate_neural_speech(text: str) -> str:
    try:
        clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()
        communicate = edge_tts.Communicate(clean_text, voice="hi-IN-SwaraNeural")
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])
        return base64.b64encode(audio_stream.getvalue()).decode("utf-8")
    except Exception:
        return ""

# --- Telegram Bot Handler ---
async def run_telegram_gateway():
    if not TELEGRAM_BOT_TOKEN:
        return
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        save_boss_chat_id(str(chat_id))
        await update.message.reply_text("नमस्ते Boss! Maya Sovereign Core सक्रिय है। सभी बैकग्राउंड टास्क्स और फाइल्स यहाँ रियल-टाइम में सिंक होंगी।")

    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        save_boss_chat_id(str(chat_id))
        text = update.message.text.strip()

        decision = await master_router(text)
        intent = decision.get("intent", "chat")
        payload = decision.get("task_payload") or text

        if intent == "generate_image":
            img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(payload)}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
            try:
                await update.message.reply_photo(photo=img_url, caption=f"✨ Boss, इमेज तैयार है:\n🎯 {payload}")
            except Exception:
                await update.message.reply_text(f"Boss, लिंक: {img_url}")

        elif intent == "new_heavy_task":
            tid = f"task_{int(time.time())}"
            asyncio.create_task(run_autonomous_worker(tid, payload))
            await update.message.reply_text("Boss, मैंने बैकग्राउंड में काम शुरू कर दिया है। पूरा होते ही यहाँ फ़ाइल और रिपोर्ट भेज दूँगी।")

        elif intent == "modify_task":
            tid = decision.get("task_id")
            tasks = load_json(TASKS_FILE, {"active": {}, "completed": []})
            active = tasks.get("active", {})
            target_id = tid if tid in active else (list(active.keys())[-1] if active else None)
            if target_id:
                active[target_id].setdefault("modifications", []).append(payload)
                save_json(TASKS_FILE, tasks)
                await update.message.reply_text(f"Boss, रनिंग टास्क `{active[target_id]['prompt'][:30]}...` में नया बदलाव जोड़ दिया गया है।")
            else:
                await update.message.reply_text("Boss, कोई एक्टिव टास्क नहीं मिला, मैं इसे नए टास्क के रूप में शुरू कर देती हूँ।")
                asyncio.create_task(run_autonomous_worker(f"task_{int(time.time())}", payload))

        else:
            await update.message.reply_text(decision.get("voice_response", "जी Boss!"))

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

# --- Render Never-Sleep Watchdog ---
@app.on_event("startup")
async def startup():
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
    tasks = load_json(TASKS_FILE, {"active": {}, "completed": []})
    return {"status": "Sovereign Master Active", "active_tasks_count": len(tasks.get("active", {}))}

# --- WebSocket Live Voice & Dynamic Executive Stream ---
@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    ACTIVE_WEBSOCKETS.append(ws)

    welcome_text = "नमस्ते Boss! मैं ऑनलाइन हूँ, कहिए क्या हुक्म है?"
    welcome_audio = await generate_neural_speech(welcome_text)
    if welcome_audio:
        await ws.send_json({"type": "audio", "data": welcome_audio})
        await ws.send_json({"type": "reply_text", "text": welcome_text})

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            user_query = ""

            if msg.get("type") == "audio_blob" and groq_client:
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

            elif msg.get("type") == "query":
                user_query = msg.get("text", "").strip()

            if user_query:
                await ws.send_json({"type": "transcript", "text": user_query})

                decision = await master_router(user_query)
                intent = decision.get("intent", "chat")
                voice_msg = decision.get("voice_response", "जी Boss!")
                payload = decision.get("task_payload") or user_query
                screen_doc = decision.get("screen_content", "")

                # 1. Heavy Project / Website / Research Trigger
                if intent == "new_heavy_task":
                    tid = f"task_{int(time.time())}"
                    asyncio.create_task(run_autonomous_worker(tid, payload))

                # 2. Mid-Call Task Editing
                elif intent == "modify_task":
                    tid = decision.get("task_id")
                    tasks = load_json(TASKS_FILE, {"active": {}, "completed": []})
                    active = tasks.get("active", {})
                    target_id = tid if tid in active else (list(active.keys())[-1] if active else None)
                    if target_id:
                        active[target_id].setdefault("modifications", []).append(payload)
                        save_json(TASKS_FILE, tasks)
                        voice_msg = "Boss, बैकग्राउंड टास्क में यह नया बदलाव जोड़ दिया है।"

                # 3. Image Generation
                elif intent == "generate_image":
                    img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(payload)}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                    await ws.send_json({"type": "image", "url": img_url})
                    asyncio.create_task(dispatch_to_telegram(photo_url=img_url, caption=f"✨ Live Image: {payload}"))

                # 4. Long Script/Report Projection
                if screen_doc:
                    await ws.send_json({"type": "document", "content": screen_doc})
                    asyncio.create_task(dispatch_to_telegram(text=f"📋 **LIVE SCRIPT / PROJECTION**\n\n{screen_doc}"))

                # 5. Crisp Voice Output
                await ws.send_json({"type": "reply_text", "text": voice_msg})
                speech_b64 = await generate_neural_speech(voice_msg)
                if speech_b64:
                    await ws.send_json({"type": "audio", "data": speech_b64})

    except WebSocketDisconnect:
        if ws in ACTIVE_WEBSOCKETS:
            ACTIVE_WEBSOCKETS.remove(ws)

@app.get("/", response_class=HTMLResponse)
async def home():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Maya Sovereign OS Active</h1>"
