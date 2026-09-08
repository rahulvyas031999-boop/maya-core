import os
import io
import re
import time
import json
import base64
import asyncio
import urllib.parse
from typing import Dict, Any

import httpx
import edge_tts

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

from groq import Groq
from google import genai

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from agent_loop import run_react_agent
from task_queue import (
    create_task,
    append_modification,
    get_latest_active_task_id,
    get_task,
    update_task_status,
    get_active_tasks_summary,
    get_unprocessed_tasks,
)

from workspace_manager import (
    list_artifacts,
    get_workspace_path,
    WORKSPACE_DIR,
)

# ============================================================
# APPLICATION INITIALIZATION
# ============================================================

app = FastAPI(title="Maya Sovereign Meta-Agent OS")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})
    if GEMINI_API_KEY
    else None
)

STATE_FILE = os.getenv("STATE_FILE_PATH", "maya_state.json")
CURRENT_ACTIVE_WS: WebSocket | None = None

# ============================================================
# PERSISTENT ATOMIC STORAGE
# ============================================================

def load_json(filepath: str, default: Any) -> Any:
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[STORAGE READ ERROR] {exc}")
        return default

def save_json(filepath: str, data: Any) -> None:
    try:
        temp = filepath + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, filepath)
    except Exception as exc:
        print(f"[STORAGE WRITE ERROR] {exc}")

def get_boss_chat_id() -> str:
    return str(load_json(STATE_FILE, {}).get("boss_chat_id", ""))

def save_boss_chat_id(chat_id: str) -> None:
    data = load_json(STATE_FILE, {})
    data["boss_chat_id"] = str(chat_id)
    save_json(STATE_FILE, data)

# ============================================================
# CRASH-PROOF WEBSOCKET WRAPPER
# ============================================================

async def safe_send_json(ws: WebSocket | None, payload: dict) -> bool:
    if ws is None:
        return False
    try:
        if getattr(ws.client_state, "name", "") == "CONNECTED":
            await ws.send_json(payload)
            return True
    except Exception as exc:
        print(f"[WS SHIELD] Dropped payload on dead socket: {exc}")
    return False

# ============================================================
# TELEGRAM DISPATCH GATEWAY
# ============================================================

async def dispatch_to_telegram(
    text: str | None = None,
    photo_url: str | None = None,
    document_path: str | None = None,
    caption: str = "",
):
    chat_id = get_boss_chat_id()
    if not chat_id or not TELEGRAM_BOT_TOKEN:
        return

    try:
        async with httpx.AsyncClient() as client:
            if photo_url:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    json={
                        "chat_id": chat_id,
                        "photo": photo_url,
                        "caption": caption or "✨ Visual Delivery",
                    },
                    timeout=20,
                )

            if document_path:
                safe_document = get_workspace_path(
                    os.path.relpath(document_path, WORKSPACE_DIR)
                )
                if os.path.isfile(safe_document):
                    file_name = os.path.basename(safe_document)
                    with open(safe_document, "rb") as f:
                        files = {"document": (file_name, f)}
                        await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                            data={"chat_id": chat_id, "caption": caption or f"📁 {file_name}"},
                            files=files,
                            timeout=30,
                        )

            if text:
                chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)]
                for chunk in chunks:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                        timeout=15,
                    )
    except Exception as exc:
        print(f"[TELEGRAM DISPATCH ERROR] {exc}")

# ============================================================
# DECOUPLED ASYNC BACKGROUND WORKER
# ============================================================

async def run_autonomous_worker(task_id: str, initial_prompt: str):
    print(f"[WORKER START] Task: {task_id}")
    try:
        update_task_status(task_id, "processing")
        task_info = get_task(task_id)

        modifications = []
        if task_info:
            modifications = task_info.get("modifications", []) or []

        full_spec = initial_prompt
        if modifications:
            full_spec += "\n\n[USER MODIFICATIONS APPLIED]:\n" + "\n".join(f"- {m}" for m in modifications)

        final_delivery = await run_react_agent(full_spec)
        success = not final_delivery.startswith("[AGENT_ERROR]")

        update_task_status(task_id, "completed" if success else "failed", final_delivery)

        report_msg = (
            "🚀 MAYA AUTONOMOUS TASK REPORT\n\n"
            f"Prompt: {initial_prompt}\n\n"
            f"{final_delivery}"
        )
        await dispatch_to_telegram(text=report_msg)

        artifacts = list_artifacts()
        if artifacts:
            latest = artifacts[-1]
            try:
                actual_path = get_workspace_path(latest["relative_path"])
                await dispatch_to_telegram(
                    document_path=actual_path,
                    caption=f"📁 Generated File: {latest['filename']}",
                )
            except Exception as exc:
                print(f"[ARTIFACT ERROR] {exc}")

        global CURRENT_ACTIVE_WS
        if CURRENT_ACTIVE_WS:
            await safe_send_json(
                CURRENT_ACTIVE_WS,
                {
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": success,
                    "text": "Boss, बैकग्राउंड टास्क पूरा हो गया है।",
                },
            )

    except Exception as exc:
        print(f"[WORKER ERROR] {task_id}: {exc}")
        update_task_status(task_id, "failed", f"Worker error: {exc}")
        await dispatch_to_telegram(text=f"❌ Task {task_id} failed:\n{exc}")

# ============================================================
# MASTER ROUTER (Intent Classifier)
# ============================================================

def extract_clean_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return {}

async def master_router(user_input: str) -> Dict[str, Any]:
    user_input = user_input.strip()
    if not user_input:
        return {
            "intent": "chat",
            "voice_response": "जी Boss, मैं सुन रही हूँ।",
            "task_payload": "",
            "screen_content": "",
        }

    clean = user_input.lower()
    explicit_image_cmd = any(
        k in clean for k in [
            "photo banao", "image banao", "tasveer banao", 
            "generate image", "chitra banao", "इमेज बनाओ", "फोटो बनाओ"
        ]
    )

    active_summary = get_active_tasks_summary()

    router_prompt = f"""
You are Maya, a female AI executive.
Always answer in Hindi/Hinglish.
Use female grammar: "करती हूँ", "बताती हूँ", "कर रही हूँ".
Never use male forms: "करता हूँ", "बताता हूँ".

Classify the user's request into: chat | new_heavy_task | modify_task | generate_image

ACTIVE TASKS:
{json.dumps(active_summary, ensure_ascii=False)}

USER:
{user_input}

Return ONLY JSON:
{{
  "intent": "chat",
  "voice_response": "one short crisp Hindi sentence",
  "task_id": "",
  "task_payload": "{user_input}",
  "screen_content": ""
}}
"""

    decision = {}

    if groq_client:
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=[
                        {"role": "system", "content": "You are Maya Master Router. Return valid JSON only with female grammar."},
                        {"role": "user", "content": router_prompt},
                    ],
                    response_format={"type": "json_object"},
                    # FIX: 70 tokens was too tight - the JSON payload includes
                    # task_payload (a full copy of user_input) plus several
                    # other fields, so long user messages were getting the
                    # response truncated mid-JSON, causing extract_clean_json
                    # to silently fail and fall back to a generic "chat" intent.
                    max_tokens=300,
                ),
            )
            decision = extract_clean_json(response.choices[0].message.content)
        except Exception as exc:
            print(f"[ROUTER GROQ WARNING] {exc}. Switching to Gemini...")

    if not decision and gemini_client:
        try:
            response = await asyncio.to_thread(
                lambda: gemini_client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=router_prompt,
                )
            )
            decision = extract_clean_json(response.text)
        except Exception as exc:
            print(f"[ROUTER GEMINI WARNING] {exc}")

    valid_intents = {"chat", "new_heavy_task", "modify_task", "generate_image"}
    if decision.get("intent") not in valid_intents:
        decision = {
            "intent": "chat",
            "voice_response": "जी Boss, बताइए मैं क्या करूँ?",
            "task_payload": user_input,
            "screen_content": "",
        }

    if decision.get("intent") == "generate_image" and not explicit_image_cmd:
        decision["intent"] = "chat"
        decision["voice_response"] = "जी Boss, क्या आप इसकी इमेज बनवाना चाहते हैं?"

    decision.setdefault("task_payload", user_input)
    decision.setdefault("voice_response", "जी Boss, समझ गई।")
    return decision

# ============================================================
# NEURAL SPEECH SYNTHESIS (Edge-TTS)
# ============================================================

async def generate_neural_speech(text: str) -> str:
    if not text:
        return ""
    try:
        clean = text.replace("*", "").replace("#", "").replace("`", "").strip()
        audio = io.BytesIO()
        communicate = edge_tts.Communicate(clean, voice="hi-IN-SwaraNeural")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
        return base64.b64encode(audio.getvalue()).decode()
    except Exception as exc:
        print(f"[TTS SYNTHESIS ERROR] {exc}")
        return ""

# ============================================================
# TELEGRAM SERVICE
# ============================================================

async def run_telegram_gateway():
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

        async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.effective_chat or not update.message:
                return
            save_boss_chat_id(str(update.effective_chat.id))
            await update.message.reply_text("नमस्ते Boss! Maya Core online है।")

        async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message or not update.effective_chat:
                return
            text = (update.message.text or "").strip()
            if not text:
                return

            save_boss_chat_id(str(update.effective_chat.id))
            decision = await master_router(text)
            intent = decision.get("intent", "chat")
            payload = decision.get("task_payload") or text

            if intent == "generate_image":
                image_url = (
                    "https://image.pollinations.ai/prompt/"
                    + urllib.parse.quote(payload)
                    + "?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                )
                try:
                    await update.message.reply_photo(
                        photo=image_url,
                        caption="✨ Boss, image तैयार है.",
                    )
                except Exception:
                    await update.message.reply_text(image_url)

            elif intent == "new_heavy_task":
                task_id = f"task_{time.time_ns()}"
                create_task(task_id, payload)
                asyncio.create_task(run_autonomous_worker(task_id, payload))
                await update.message.reply_text("Boss, काम background में शुरू कर रही हूँ।")

            elif intent == "modify_task":
                task_id = decision.get("task_id") or get_latest_active_task_id()
                if task_id and append_modification(task_id, payload):
                    await update.message.reply_text("Boss, running task में modification जोड़ दिया है।")
                else:
                    task_id = f"task_{time.time_ns()}"
                    create_task(task_id, payload)
                    asyncio.create_task(run_autonomous_worker(task_id, payload))
                    await update.message.reply_text("Boss, नया task शुरू कर रही हूँ।")

            else:
                await update.message.reply_text(decision.get("voice_response", "जी Boss!"))

        application.add_handler(CommandHandler("start", start_cmd))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
    except Exception as exc:
        print(f"[TELEGRAM ENGINE ERROR] {exc}")

# ============================================================
# LIFECYCLE & HTTP ROUTES
# ============================================================

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
        asyncio.create_task(run_autonomous_worker(t["task_id"], t["prompt"]))

@app.get("/health")
async def health():
    return {"status": "Maya Core Online", "active_tasks": len(get_active_tasks_summary())}

@app.get("/artifacts")
async def get_artifacts_list():
    return {"workspace_files": list_artifacts()}

@app.get("/artifacts/{file_path:path}")
async def download_or_view_artifact(file_path: str):
    try:
        safe_path = get_workspace_path(file_path)
        if os.path.exists(safe_path) and os.path.isfile(safe_path):
            return FileResponse(safe_path)
        return {"error": "File not found"}
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# WEBSOCKET LIVE VOICE ENGINE (Deterministic / No Filter List)
# ============================================================

@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    global CURRENT_ACTIVE_WS
    CURRENT_ACTIVE_WS = ws

    try:
        welcome_text = "नमस्ते Boss! मैं ऑनलाइन हूँ, कहिए क्या हुक्म है?"
        welcome_audio = await generate_neural_speech(welcome_text)
        if welcome_audio:
            await safe_send_json(ws, {"type": "audio", "data": welcome_audio})
            await safe_send_json(ws, {"type": "reply_text", "text": welcome_text})
    except Exception as ge:
        print(f"[WELCOME GREETING ERROR]: {ge}")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            user_query = ""

            if msg.get("type") == "query":
                user_query = msg.get("text", "").strip()

            elif msg.get("type") == "audio_blob" and groq_client:
                try:
                    wav_bytes = base64.b64decode(msg.get("data", ""))
                    incoming_mime = msg.get("mime", "audio/webm").lower()

                    ext = ".webm"
                    if "mp4" in incoming_mime:
                        ext = ".mp4"
                    elif "ogg" in incoming_mime:
                        ext = ".ogg"
                    elif "wav" in incoming_mime:
                        ext = ".wav"

                    audio_file = io.BytesIO(wav_bytes)
                    audio_file.name = f"audio{ext}"

                    loop = asyncio.get_running_loop()
                    # Context conditioning with zero temperature eliminates silence hallucinations
                    transcription = await loop.run_in_executor(
                        None,
                        lambda: groq_client.audio.transcriptions.create(
                            file=audio_file, 
                            model="whisper-large-v3-turbo", 
                            language="hi",
                            prompt="नमस्ते माया, मुझे आपसे कुछ पूछना है।",
                            temperature=0.0
                        )
                    )
                    cand = transcription.text.strip()
                    if len(cand) > 1:
                        user_query = cand

                except Exception as e:
                    print(f"[WHISPER TRANSCRIPTION ERROR]: {e}")

            if user_query:
                await safe_send_json(ws, {"type": "transcript", "text": user_query})

                decision = await master_router(user_query)
                intent = decision.get("intent", "chat")
                voice_msg = decision.get("voice_response", "जी Boss!")
                payload = decision.get("task_payload") or user_query

                if intent == "new_heavy_task":
                    tid = f"task_{time.time_ns()}"
                    create_task(tid, payload)
                    asyncio.create_task(run_autonomous_worker(tid, payload))

                elif intent == "modify_task":
                    tid = decision.get("task_id") or get_latest_active_task_id()
                    if tid and append_modification(tid, payload):
                        voice_msg = "Boss, बैकग्राउंड टास्क में नया बदलाव जोड़ दिया है।"
                    else:
                        new_tid = f"task_{time.time_ns()}"
                        create_task(new_tid, payload)
                        asyncio.create_task(run_autonomous_worker(new_tid, payload))
                        voice_msg = "Boss, नया बैकग्राउंड टास्क शुरू कर रही हूँ।"

                elif intent == "generate_image":
                    img_url = (
                        "https://image.pollinations.ai/prompt/"
                        + urllib.parse.quote(payload)
                        + "?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                    )
                    await safe_send_json(ws, {"type": "image", "url": img_url})
                    asyncio.create_task(
                        dispatch_to_telegram(photo_url=img_url, caption=f"✨ Live Image: {payload}")
                    )

                await safe_send_json(ws, {"type": "reply_text", "text": voice_msg})
                speech_b64 = await generate_neural_speech(voice_msg)
                if speech_b64:
                    await safe_send_json(ws, {"type": "audio", "data": speech_b64})

    except WebSocketDisconnect:
        print("[WS INFO] WebSocket closed gracefully by client.")
    except Exception as err:
        print(f"[WS RUNTIME ERROR] {err}")
    finally:
        if CURRENT_ACTIVE_WS == ws:
            CURRENT_ACTIVE_WS = None

@app.get("/", response_class=HTMLResponse)
async def home():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Maya Sovereign OS Active</h1>"
