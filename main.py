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
    remember_fact,
    recall_memory,
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
_TELEGRAM_USERNAME_CACHE: str | None = None

# ============================================================
# NETWORK RESILIENCE TUNING
# ============================================================
ROUTER_TIMEOUT_SECONDS = 10
WHISPER_TIMEOUT_SECONDS = 15
TTS_TIMEOUT_SECONDS = 10
WS_IDLE_TIMEOUT_SECONDS = 40

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

async def get_telegram_bot_username() -> str | None:
    global _TELEGRAM_USERNAME_CACHE
    if _TELEGRAM_USERNAME_CACHE:
        return _TELEGRAM_USERNAME_CACHE
    if not TELEGRAM_BOT_TOKEN:
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
                timeout=10,
            )
            data = resp.json()
            username = data.get("result", {}).get("username")
            if username:
                _TELEGRAM_USERNAME_CACHE = username
                return username
    except Exception as exc:
        print(f"[TELEGRAM GETME ERROR] {exc}")
    return None

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

HALLUCINATION_BLACKLIST = {
    "thank you", "thanks for watching", "subtitles", "subscribe",
    "झाल", "जय हिंद", "आप सभी को धन्यवाद", "धन्यवाद",
}

def is_hallucinated_transcript(text: str) -> bool:
    normalized = text.strip().lower().strip(".,!?।")
    return normalized in HALLUCINATION_BLACKLIST

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

    explicit_telegram_cmd = any(
        k in clean for k in [
            "telegram pe switch", "telegram par switch", "telegram mode",
            "telegram pe bhej", "telegram par bhej", "switch to telegram",
            "low bandwidth mode", "टेलीग्राम पर स्विच", "टेलीग्राम मोड",
            "टेलीग्राम पे स्विच",
        ]
    )
    if explicit_telegram_cmd:
        return {
            "intent": "switch_telegram",
            "voice_response": "ठीक है Boss, Telegram मोड पर भेज रही हूँ।",
            "task_payload": "",
            "screen_content": "",
        }

    explicit_remember_cmd = any(
        k in clean for k in [
            "yaad rakh", "yaad rakhna", "yaad rakho", "hamesha yaad",
            "याद रख", "याद रखना", "याद रखो", "हमेशा याद",
            "remember this", "remember that", "from now on", "always remember",
        ]
    )
    if explicit_remember_cmd:
        fact_key = f"note_{int(time.time())}"
        remember_fact(fact_key, user_input, category="boss_instructions")
        return {
            "intent": "chat",
            "voice_response": "ठीक है Boss, ये मैंने हमेशा के लिए याद रख लिया।",
            "task_payload": user_input,
            "screen_content": "",
        }

    active_summary = get_active_tasks_summary()
    known_memory = recall_memory()
    memory_context = "\n".join(
        f"- {k}: {v}" for k, v in known_memory.items()
        if k != "active_model_registry"
    ) or "(kuch bhi yaad nahi hai abhi)"

    router_prompt = f"""
You are Maya, a female AI executive.
Always answer in Hindi/Hinglish.
Use female grammar: "करती हूँ", "बताती हूँ", "कर रही हूँ".
Never use male forms: "करता हूँ", "बताता हूँ".

Classify the user's request into: chat | new_heavy_task | modify_task | generate_image

THINGS YOU ALREADY KNOW ABOUT BOSS (from long-term memory):
{memory_context}

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
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: groq_client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        messages=[
                            {"role": "system", "content": "You are Maya Master Router. Return valid JSON only with female grammar."},
                            {"role": "user", "content": router_prompt},
                        ],
                        response_format={"type": "json_object"},
                        max_tokens=300,
                    ),
                ),
                timeout=ROUTER_TIMEOUT_SECONDS,
            )
            decision = extract_clean_json(response.choices[0].message.content)
        except asyncio.TimeoutError:
            print(f"[ROUTER GROQ TIMEOUT] No response within {ROUTER_TIMEOUT_SECONDS}s. Switching to Gemini...")
        except Exception as exc:
            print(f"[ROUTER GROQ WARNING] {exc}. Switching to Gemini...")

    if not decision and gemini_client:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: gemini_client.models.generate_content(
                        model="gemini-3.6-flash",
                        contents=router_prompt,
                    )
                ),
                timeout=ROUTER_TIMEOUT_SECONDS,
            )
            decision = extract_clean_json(response.text)
        except asyncio.TimeoutError:
            print(f"[ROUTER GEMINI TIMEOUT] No response within {ROUTER_TIMEOUT_SECONDS}s.")
        except Exception as exc:
            print(f"[ROUTER GEMINI WARNING] {exc}")

    valid_intents = {"chat", "new_heavy_task", "modify_task", "generate_image", "switch_telegram"}
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
# NEURAL SPEECH SYNTHESIS (Edge-TTS) — SENTENCE STREAMING
# ============================================================

def split_into_speech_sentences(text: str, max_chars: int = 220) -> list[str]:
    if not text:
        return []

    raw_parts = re.split(r"(?<=[।.!?])\s+", text.strip())
    chunks: list[str] = []
    buffer = ""

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if buffer and len(buffer) + len(part) + 1 > max_chars:
            chunks.append(buffer)
            buffer = part
        else:
            buffer = f"{buffer} {part}".strip()

    if buffer:
        chunks.append(buffer)

    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars * 2:
            final.append(chunk)
        else:
            final.extend(chunk[i:i + max_chars] for i in range(0, len(chunk), max_chars))
    return final

async def synthesize_sentence(text: str) -> str:
    clean = text.replace("*", "").replace("#", "").replace("`", "").strip()
    if not clean:
        return ""
    try:
        audio = io.BytesIO()
        communicate = edge_tts.Communicate(clean, voice="hi-IN-SwaraNeural")

        async def _run():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.write(chunk["data"])

        await asyncio.wait_for(_run(), timeout=TTS_TIMEOUT_SECONDS)
        return base64.b64encode(audio.getvalue()).decode()
    except asyncio.TimeoutError:
        print(f"[TTS TIMEOUT] Sentence synthesis exceeded {TTS_TIMEOUT_SECONDS}s, skipping.")
        return ""
    except Exception as exc:
        print(f"[TTS SYNTHESIS ERROR] {exc}")
        return ""

async def stream_neural_speech(ws: WebSocket, text: str) -> bool:
    sentences = split_into_speech_sentences(text)
    sent_any = False

    for sentence in sentences:
        if getattr(ws.client_state, "name", "") != "CONNECTED":
            break
        audio_b64 = await synthesize_sentence(sentence)
        if audio_b64:
            delivered = await safe_send_json(ws, {"type": "audio_chunk", "data": audio_b64})
            sent_any = sent_any or delivered

    await safe_send_json(ws, {"type": "audio_end"})
    return sent_any

# ============================================================
# TELEGRAM SERVICE (Hardened against 409 Conflict)
# ============================================================

async def run_telegram_gateway():
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true",
                timeout=10.0
            )

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
                    await update.message.reply_photo(photo=image_url, caption="✨ Boss, image तैयार है.")
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

@app.get("/telegram-link")
async def get_telegram_link():
    username = await get_telegram_bot_username()
    return {"url": f"https://t.me/{username}" if username else None}

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
# WEBSOCKET LIVE VOICE ENGINE
# ============================================================

@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    global CURRENT_ACTIVE_WS

    if CURRENT_ACTIVE_WS is not None and CURRENT_ACTIVE_WS is not ws:
        try:
            await CURRENT_ACTIVE_WS.close(code=1000, reason="Replaced by new session")
        except Exception as close_err:
            print(f"[OLD WS CLOSE WARNING] {close_err}")

    CURRENT_ACTIVE_WS = ws

    try:
        welcome_text = "नमस्ते Boss! मैं ऑनलाइन हूँ, कहिए क्या हुक्म है?"
        await safe_send_json(ws, {"type": "reply_text", "text": welcome_text})
        await stream_neural_speech(ws, welcome_text)
    except Exception as ge:
        print(f"[WELCOME GREETING ERROR]: {ge}")

    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=WS_IDLE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                print("[WS HEARTBEAT] No client activity in idle window, closing stale socket.")
                break

            msg = json.loads(data)

            if msg.get("type") == "ping":
                await safe_send_json(ws, {"type": "pong", "ts": msg.get("ts")})
                continue

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
                    transcription = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: groq_client.audio.transcriptions.create(
                                file=audio_file, 
                                model="whisper-large-v3-turbo", 
                                language="hi",
                                prompt="नमस्ते माया, मुझे आपसे कुछ पूछना है।",
                                temperature=0.0
                            )
                        ),
                        timeout=WHISPER_TIMEOUT_SECONDS,
                    )
                    cand = transcription.text.strip()
                    
                    print(f"[WHISPER HEARD]: '{cand}' (Bytes: {len(wav_bytes)})")

                    if len(cand) > 1 and not is_hallucinated_transcript(cand):
                        user_query = cand

                except asyncio.TimeoutError:
                    print(f"[WHISPER TIMEOUT] No response within {WHISPER_TIMEOUT_SECONDS}s.")
                    await safe_send_json(ws, {
                        "type": "reply_text",
                        "text": "Boss, नेटवर्क थोड़ा धीमा लग रहा है, फिर से बोलिए।",
                    })
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

                elif intent == "switch_telegram":
                    tg_username = await get_telegram_bot_username()
                    tg_url = f"https://t.me/{tg_username}" if tg_username else None
                    await safe_send_json(ws, {"type": "telegram_redirect", "url": tg_url})
                    if not tg_url:
                        voice_msg = "Boss, Telegram अभी configure नहीं है, ये feature उपलब्ध नहीं है।"

                await safe_send_json(ws, {"type": "reply_text", "text": voice_msg})
                await stream_neural_speech(ws, voice_msg)

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
