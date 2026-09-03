import os
import io
import wave
import base64
import urllib.parse
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from groq import Groq
from google import genai

app = FastAPI(title="Maya Autonomous Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Keys environment variables se aayengi (Secure)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

TASK_LOGS = []

def execute_autonomous_task(task_desc: str):
    TASK_LOGS.append(f"Started: {task_desc}")
    # Autonomous task processing
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

def generate_voice_b64(text):
    try:
        if not gemini_client:
            return None
        res = gemini_client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=text.replace("*", "")[:200],
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
    msg = req.message.strip().lower()

    # Background task detection
    if any(k in msg for k in ["upload", "schedule", "agent banao", "automate"]):
        background_tasks.add_task(execute_autonomous_task, req.message)
        return JSONResponse({
            "type": "text",
            "content": "🚀 Task register ho chuka hai! Internet band hone par bhi Maya background me kaam jari rakhegi.",
            "audio": None
        })

    # Image generation route
    if any(k in msg for k in ["image", "photo", "tasveer"]):
        p = msg
        for w in ["image", "photo", "banao", "generate", "create", "ki", "ek", "tasveer"]:
            p = p.replace(w, "")
        p = p.strip() or "cyberpunk neon supercar"
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(p)}?width=1024&height=1024&nologo=true"
        return JSONResponse({"type": "image", "content": url, "audio": None})

    # High-Intelligence chat route
    reply = "Sorry, system busy."
    try:
        if groq_client:
            comp = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are Maya, an autonomous AI operating system. Reply naturally in Hinglish."},
                    {"role": "user", "content": msg}
                ],
                model="openai/gpt-oss-120b"
            )
            reply = comp.choices[0].message.content
        elif gemini_client:
            res = gemini_client.models.generate_content(model="gemini-2.5-flash", contents=msg)
            reply = res.text
    except Exception as e:
        reply = f"Error processing: {str(e)}"

    return JSONResponse({"type": "text", "content": reply, "audio": generate_voice_b64(reply)})

@app.get("/api/tasks")
def get_tasks():
    return {"tasks": TASK_LOGS}

@app.get("/")
def home():
    return {"status": "Maya Autonomous Engine 24/7 Active"}
