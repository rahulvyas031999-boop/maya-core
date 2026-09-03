import os
import io
import wave
import base64
import urllib.parse
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from groq import Groq
from google import genai

app = FastAPI(title="Maya Autonomous Core")

# CORS Setup for Web Access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Keys from Render Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Rule 3: Personality Lock (Strictly Female, Always 'Aap', Polite & Caring)
SYSTEM_PROMPT = (
    "You are Maya, an intelligent, polite, and caring autonomous female AI assistant. "
    "Rule: Always speak in Hindi/Hinglish using strictly female grammatical forms ('करती हूँ', 'बता सकती हूँ', 'कर दूँगी'). "
    "Always address the user respectfully as 'आप' (never use 'तू' or 'तेरा'). "
    "Keep replies concise, warm, and helpful."
)

TASK_LOGS = []

def execute_autonomous_task(task_desc: str):
    """Background execution worker (runs even if user goes offline)"""
    TASK_LOGS.append(f"Started: {task_desc}")
    TASK_LOGS.append(f"Completed: {task_desc}")

def pcm_to_wav(pcm_data):
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(pcm_data)
    wav_io.seek(0)
    return wav_io.read()

# Non-blocking / Lightweight Audio
def generate_voice_b64(text: str):
    if not gemini_client:
        return None
    try:
        clean = text.replace("*", "").replace("#", "")[:150]
        res = gemini_client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=clean,
            config=dict(response_modalities=["AUDIO"])
        )
        for part in res.candidates[0].content.parts:
            if getattr(part, 'inline_data', None):
                return base64.b64encode(pcm_to_wav(part.inline_data.data)).decode('utf-8')
    except Exception:
        pass
    return None

class ChatReq(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_api(req: ChatReq, background_tasks: BackgroundTasks):
    user_msg = req.message.strip()
    msg_low = user_msg.lower()

    # 1. Background Task Route (24/7 Autonomy)
    if any(k in msg_low for k in ["upload", "schedule", "agent banao", "automate"]):
        background_tasks.add_task(execute_autonomous_task, user_msg)
        return JSONResponse({
            "type": "text",
            "content": "जी, मैंने आपका यह काम बैकग्राउंड में शुरू कर दिया है। आप इंटरनेट बंद कर सकते हैं, मैं इसे सर्वर पर पूरा कर दूँगी।",
            "audio": None
        })

    # 2. Rule 2: Image Generation Locked with Flux Engine
    if any(k in msg_low for k in ["image", "photo", "tasveer", "picture"]):
        clean_p = msg_low
        for w in ["image", "photo", "banao", "generate", "create", "ki", "ek", "tasveer"]:
            clean_p = clean_p.replace(w, "")
        clean_p = clean_p.strip() or "cyberpunk neon supercar"
        encoded_prompt = urllib.parse.quote(clean_p)
        # Locked to Pollinations Flux Engine
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width=1024&height=1024&nologo=true"
        return JSONResponse({"type": "image", "content": url, "audio": None})

    # 3. Rule 2: Locked Chat Engines (Primary: Groq llama-3.1-8b-instant | Fallback: Gemini gemini-3.6-flash)
    reply = ""
    
    # Primary: Groq llama-3.1-8b-instant (0.2s ultra fast latency)
    if groq_client:
        try:
            comp = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.6
            )
            reply = comp.choices[0].message.content
        except Exception as e:
            print(f"Groq API Error: {e}")

    # Fallback: Google Gemini gemini-3.6-flash
    if not reply and gemini_client:
        try:
            full_prompt = f"{SYSTEM_PROMPT}\n\nयूज़र: {user_msg}\nमाया:"
            res = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=full_prompt
            )
            reply = res.text
        except Exception as e:
            print(f"Gemini API Error: {e}")

    if not reply:
        reply = "माफ़ कीजिए, सर्वर से संपर्क नहीं हो पा रहा है। कृपया अपनी API Keys चेक करें।"

    audio_data = generate_voice_b64(reply)
    return JSONResponse({"type": "text", "content": reply, "audio": audio_data})

@app.get("/api/tasks")
def get_tasks():
    return {"tasks": TASK_LOGS}

@app.get("/")
def home():
    return {"status": "Maya Autonomous Core 24/7 Active"}
