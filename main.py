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
from fastapi.responses import HTMLResponse, FileResponse
from groq import Groq
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ReAct & Workspace Modules
from agent_loop import run_react_agent
from task_queue import (
    create_task,
    append_modification,
    get_latest_active_task_id,
    get_task,
    update_task_status,
    get_active_tasks_summary,
    get_unprocessed_tasks
)
from workspace_manager import list_artifacts, get_workspace_path, WORKSPACE_DIR

app = FastAPI(title="Maya Sovereign Meta-Agent OS")

# --- Environment Setup ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

STATE_FILE = "maya_state.json"
CURRENT_ACTIVE_WS: WebSocket = None  # Single Active WebSocket Lock

GHOST_PHRASES = [
    "subtitles", "thank you", "watching", "amara.org", "subscribe", 
    "you", "bye", "thanks", "dhanyawad", "foreign", "[music]"
]

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

async def dispatch_to_telegram(text: str = None, photo_url: str = None, document_path: str = None, caption: str = ""):
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
            if document_path and os.path.exists(document_path):
                file_name = os.path.basename(document_path)
                with open(document_path, "rb") as f:
                    files = {"document": (file_name, f.read())}
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                        data={"chat_id": chat_id, "caption": caption or f"📁 Generated File: {file_name}"},
                        files=files,
                        timeout=30.0
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

# --- Decoupled Heavy Worker (Runs completely independent of live voice call) ---
async def run_autonomous_worker(task_id: str, initial_prompt: str):
    print(f"[HEAVY WORKER] Task {task_id} launched: {initial_prompt}")
    update_task_status(task_id, "processing")
    await asyncio.sleep(2)

    task_info = get_task(task_id)
    mods = task_info.get("modifications", []) if task_info else []
    full_spec = initial_prompt
    if mods:
        full_spec += "\n\n[USER MODIFICATIONS APPLIED MID-CALL]:\n" + "\n".join([f"- {m}" for m in mods])

    # ReAct agent execution
    final_delivery = await run_react_agent(full_spec)
    update_task_status(task_id, "completed", final_delivery)

    # 1. Telegram Dispatch
    report_msg = f"🚀 **AUTONOMOUS TASK DEPLOYED, BOSS!**\n\n📌 **Task:** `{initial_prompt}`\n\n{final_delivery}"
    await dispatch_to_telegram(text=report_msg)

    # 2. Telegram File Dispatch
    all_files = list_artifacts()
    if all_files:
        latest_file = all_files[-1]
        actual_file_path = get_workspace_path(latest_file["relative_path"])
        await dispatch_to_telegram(
            document_path=actual_file_path, 
            caption=f"📁 Boss, यहाँ आपकी जनरेटेड फ़ाइल है: {latest_file['filename']}"
        )

    # 3. Live WebSocket Alert (Non-blocking)
    global CURRENT_ACTIVE_WS
    if CURRENT_ACTIVE_WS:
        try:
            await CURRENT_ACTIVE_WS.send_json({
                "type": "reply_text",
                "text": f"Boss, टास्क पूरा हो गया है। फ़ाइल और रिपोर्ट टेलीग्राम पर भेज दी है।"
            })
        except Exception:
            pass

def extract_clean_json(text: str) -> Dict[str, Any]:
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception:
        return {}

async def master_router(user_input: str) -> Dict[str, Any]:
    words = user_input.strip().split()
    if len(words) <= 2 and not any(w in user_input.lower() for w in ["photo", "image", "tasveer"]):
        return {
            "intent": "chat",
            "voice_response": "जी Boss, बताइए मैं क्या करूँ?",
            "task_payload": user_input,
            "screen_content": ""
        }

    active_summary = get_active_tasks_summary()

    router_prompt = (
        f"You are Maya, an ultra-smart, loyal FEMALE AI Executive for Boss.\n"
        f"GENDER RULE: Strictly speak as a female in Hindi/Hinglish (ALWAYS use 'करती हूँ', 'बताती हूँ', 'देखती हूँ'. NEVER use male 'करता हूँ').\n"
        f"ACTIVE BACKGROUND TASKS: {json.dumps(active_summary, ensure_ascii=False)}\n"
        f"BOSS INPUT: \"{user_input}\"\n\n"
        "Return STRICT JSON only:\n"
        "{\n"
        "  \"intent\": \"chat\" | \"new_heavy_task\" | \"modify_task\" | \"generate_image\",\n"
        "  \"voice_response\": \"Strictly 1 natural, crisp female sentence in Hindi/Hinglish to speak to Boss\",\n"
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
                        {"role": "system", "content": "You are Maya. Strictly output JSON with female Hindi grammar."},
                        {"role": "user", "content": router_prompt}
                    ],
                    model="openai/gpt-oss-20b",
                    response_format={"type": "json_object"}
                )
            )
            decision = extract_clean_json(res.choices[0].message.content)
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

# --- Safe Telegram Bot Gateway ---
async def run_telegram_gateway():
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

        async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            chat_id = update.effective_chat.id
            save_boss_chat_id(str(chat_id))
            await update.message.reply_text("नमस्ते Boss! Maya Sovereign Core सक्रिय है।")

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
                create_task(tid, payload)
                asyncio.create_task(run_autonomous_worker(tid, payload))
                await update.message.reply_text("Boss, मैंने काम शुरू कर दिया है। पूरा होते ही यहाँ फ़ाइल भेज दूँगी।")

            elif intent == "modify_task":
                tid = decision.get("task_id") or get_latest_active_task_id()
                if tid and append_modification(tid, payload):
                    await update.message.reply_text("Boss, रनिंग टास्क में बदलाव जोड़ दिया गया है।")
                else:
                    new_tid = f"task_{int(time.time())}"
                    create_task(new_tid, payload)
                    asyncio.create_task(run_autonomous_worker(new_tid, payload))
                    await update.message.reply_text("Boss, नए टास्क के रूप में शुरू कर रही हूँ।")

            else:
                await update.message.reply_text(decision.get("voice_response", "जी Boss!"))

        application.add_handler(CommandHandler("start", start_cmd))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"[TELEGRAM INIT WARNING]: {e}")

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

    unprocessed = get_unprocessed_tasks()
    for t in unprocessed:
        asyncio.create_task(run_autonomous_worker(t['task_id'], t['prompt']))

@app.get("/health")
async def health():
    return {"status": "Maya Core Active", "active_tasks": len(get_active_tasks_summary())}

@app.get("/artifacts")
async def get_artifacts_list():
    return {"workspace_files": list_artifacts()}

@app.get("/artifacts/{file_path:path}")
async def download_or_view_artifact(file_path: str):
    try:
        safe_path = get_workspace_path(file_path)
        if os.path.exists(safe_path) and os.path.isfile(safe_path):
            return FileResponse(safe_path)
        return {"error": "File not found in workspace"}
    except Exception as e:
        return {"error": str(e)}

# --- WebSocket Live Voice Link (Decoupled & Single Session Lock) ---
@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    global CURRENT_ACTIVE_WS
    await ws.accept()

    if CURRENT_ACTIVE_WS is not None:
        try:
            await CURRENT_ACTIVE_WS.close()
        except Exception:
            pass
    CURRENT_ACTIVE_WS = ws

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

            # 1. Instant Text from Native Browser ASR (Fast & Zero Audio Upload)
            if msg.get("type") == "query":
                user_query = msg.get("text", "").strip()

            # 2. Audio Blob Fallback
            elif msg.get("type") == "audio_blob" and groq_client:
                try:
                    wav_bytes = base64.b64decode(msg.get("data", ""))
                    if len(wav_bytes) >= 6000:
                        audio_file = io.BytesIO(wav_bytes)
                        audio_file.name = "audio.wav"
                        loop = asyncio.get_running_loop()
                        transcription = await loop.run_in_executor(
                            None,
                            lambda: groq_client.audio.transcriptions.create(
                                file=audio_file, model="whisper-large-v3", language="hi"
                            )
                        )
                        cand = transcription.text.strip()
                        if not any(g in cand.lower() for g in GHOST_PHRASES) and len(cand) > 2:
                            user_query = cand
                except Exception as e:
                    print(f"[WHISPER ERROR]: {e}")

            if user_query:
                await ws.send_json({"type": "transcript", "text": user_query})

                decision = await master_router(user_query)
                intent = decision.get("intent", "chat")
                voice_msg = decision.get("voice_response", "जी Boss!")
                payload = decision.get("task_payload") or user_query
                screen_doc = decision.get("screen_content", "")

                # Decoupled Heavy Task Trigger (Voice loop par koi load nahi padega)
                if intent == "new_heavy_task":
                    tid = f"task_{int(time.time())}"
                    create_task(tid, payload)
                    asyncio.create_task(run_autonomous_worker(tid, payload))

                elif intent == "modify_task":
                    tid = decision.get("task_id") or get_latest_active_task_id()
                    if tid and append_modification(tid, payload):
                        voice_msg = "Boss, बैकग्राउंड टास्क में नया बदलाव जोड़ दिया है।"
                    else:
                        new_tid = f"task_{int(time.time())}"
                        create_task(new_tid, payload)
                        asyncio.create_task(run_autonomous_worker(new_tid, payload))
                        voice_msg = "Boss, मैंने नया बैकग्राउंड टास्क शुरू कर दिया है।"

                elif intent == "generate_image":
                    img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(payload)}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                    await ws.send_json({"type": "image", "url": img_url})
                    asyncio.create_task(dispatch_to_telegram(photo_url=img_url, caption=f"✨ Live Image: {payload}"))

                if screen_doc:
                    await ws.send_json({"type": "document", "content": screen_doc})
                    asyncio.create_task(dispatch_to_telegram(text=f"📋 **LIVE SCRIPT / PROJECTION**\n\n{screen_doc}"))

                # Send Crisp Voice Output
                await ws.send_json({"type": "reply_text", "text": voice_msg})
                speech_b64 = await generate_neural_speech(voice_msg)
                if speech_b64:
                    await ws.send_json({"type": "audio", "data": speech_b64})

    except WebSocketDisconnect:
        if CURRENT_ACTIVE_WS == ws:
            CURRENT_ACTIVE_WS = None

@app.get("/", response_class=HTMLResponse)
async def home():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Maya Sovereign OS Active</h1>"
