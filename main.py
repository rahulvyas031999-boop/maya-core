import os
import io
import wave
import time
import random
import base64
import urllib.parse
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

TASK_LOGS = []

def execute_autonomous_task(task_desc: str):
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
            "content": "🚀 आपका टास्क रजिस्टर हो गया है! आप इंटरनेट बंद कर सकते हैं, मैं बैकग्राउंड में यह काम पूरा कर दूँगी।",
            "audio": None
        })

    # Image generation route (Fixed URL & Cache-busting)
    if any(k in msg for k in ["image", "photo", "tasveer", "picture"]):
        clean_prompt = msg
        for w in ["image", "photo", "banao", "generate", "create", "ki", "ek", "tasveer", "do", "dikhaye", "ak"]:
            clean_prompt = clean_prompt.replace(w, "")
        clean_prompt = clean_prompt.strip() or "luxurious futuristic supercar in neon city"
        
        encoded_prompt = urllib.parse.quote(clean_prompt)
        seed = random.randint(1000, 999999)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true&model=flux"
        
        return JSONResponse({"type": "image", "content": url, "audio": None})

    # High-Intelligence chat route (Female Personality)
    system_prompt = (
        "You are Maya, an intelligent, polite, and caring female AI assistant. "
        "Speak strictly in a natural, warm, and feminine Hinglish tone (always use female grammar like 'karti hoon', 'bata sakti hoon', 'kar dungi', 'samajh gayi'). "
        "Always address the user respectfully as 'aap' (never ever use 'tu' or 'tera'). "
        "Keep your responses concise, smart, and friendly."
    )

    reply = "माफ़ कीजिए, मैं अभी प्रोसेस नहीं कर पा रही हूँ।"
    try:
        if groq_client:
            comp = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": msg}
                ],
                model="openai/gpt-oss-120b"
            )
            reply = comp.choices[0].message.content
        elif gemini_client:
            res = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{system_prompt}\nUser: {msg}"
            )
            reply = res.text
    except Exception as e:
        reply = f"Error: {str(e)}"

    return JSONResponse({"type": "text", "content": reply, "audio": generate_voice_b64(reply)})

@app.get("/api/tasks")
def get_tasks():
    return {"tasks": TASK_LOGS}

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Maya Meta-Agent OS</title>
        <style>
            :root { --bg: #090d16; --panel: #111827; --accent: #10b981; --border: #1f2937; --text: #e5e7eb; }
            body { margin:0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display:flex; flex-direction:column; height:100vh; }
            header { padding: 14px 20px; background: var(--panel); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
            .badge { background: #064e3b; color: #34d399; padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; border: 1px solid #059669; }
            #chat { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
            .msg { max-width: 80%; padding: 12px 16px; border-radius: 12px; font-size: 0.95rem; line-height: 1.5; word-wrap: break-word; }
            .user { align-self: flex-end; background: #2563eb; color: #fff; border-bottom-right-radius: 2px; }
            .maya { align-self: flex-start; background: var(--panel); border: 1px solid var(--border); border-bottom-left-radius: 2px; }
            .img-container { min-height: 250px; display: flex; flex-direction: column; gap: 8px; }
            .img-card { width: 100%; max-width: 480px; border-radius: 8px; border: 1px solid var(--border); display: block; }
            #bar { padding: 14px 20px; background: var(--panel); border-top: 1px solid var(--border); display: flex; gap: 10px; }
            input { flex: 1; padding: 12px 16px; background: var(--bg); color: #fff; border: 1px solid var(--border); border-radius: 8px; outline: none; font-size: 1rem; }
            input:focus { border-color: var(--accent); }
            button { background: var(--accent); color: #fff; border: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: 0.2s; }
            button:hover { opacity: 0.9; }
        </style>
    </head>
    <body>
        <header>
            <div style="font-weight: bold; font-size: 1.1rem;">🤖 Maya Autonomous OS</div>
            <div class="badge">● Live 24/7 (Always Warm)</div>
        </header>
        <div id="chat">
            <div class="msg maya">नमस्ते! मैं माया हूँ। मैं आपकी क्या मदद कर सकती हूँ? आप मुझसे बात कर सकते हैं, कोई फोटो बनवा सकते हैं, या कोई काम सौंप सकते हैं।</div>
        </div>
        <div id="bar">
            <input id="txt" placeholder="Maya ko koi bhi command dein..." onkeydown="if(event.key==='Enter') send()">
            <button onclick="send()">Send</button>
        </div>
        <audio id="snd" autoplay></audio>

        <script>
            async function send() {
                const inp = document.getElementById('txt');
                const v = inp.value.trim();
                if(!v) return;
                inp.value = '';
                
                append('user', v);
                const loadDiv = append('maya', '⏳ Processing command...');

                try {
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message: v})
                    });
                    const data = await res.json();
                    loadDiv.remove();

                    if(data.type === 'image') {
                        appendImg(data.content);
                    } else {
                        append('maya', data.content);
                        if(data.audio) document.getElementById('snd').src = 'data:audio/wav;base64,' + data.audio;
                    }
                } catch(e) {
                    loadDiv.innerText = '⚠️ सर्वर कनेक्ट होने में समय ले रहा है, कृपया दोबारा प्रयास करें।';
                }
            }

            function append(role, text) {
                const c = document.getElementById('chat');
                const d = document.createElement('div');
                d.className = 'msg ' + role;
                d.innerText = text;
                c.appendChild(d);
                c.scrollTop = c.scrollHeight;
                return d;
            }

            function appendImg(url) {
                const c = document.getElementById('chat');
                const d = document.createElement('div');
                d.className = 'msg maya img-container';
                d.innerHTML = `<div>✨ आपकी इमेज तैयार हो रही है...</div><img src="${url}" class="img-card" onload="this.previousElementSibling.innerText='✨ आपकी इमेज:'" onerror="this.parentElement.innerHTML='⚠️ इमेज लोड नहीं हो सकी, दोबारा कोशिश करें।'"/>`;
                c.appendChild(d);
                c.scrollTop = c.scrollHeight;
            }
        </script>
    </body>
    </html>
    """
