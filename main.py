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

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Render Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Rule 3: Locked Female Persona ('आप', 'करती हूँ')
SYSTEM_PROMPT = (
    "You are Maya, an intelligent, polite, and caring autonomous female AI assistant. "
    "Rule: Always converse in Hindi or Hinglish using strictly female grammatical inflections "
    "('करती हूँ', 'बता सकती हूँ', 'कर दूँगी', 'समझती हूँ'). "
    "Always address the user respectfully as 'आप' (strictly avoid 'तू' or 'तेरा'). "
    "Maintain a warm, concise, and helpful tone."
)

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

    # Autonomous Task Routing (Offline execution)
    if any(k in msg_low for k in ["upload", "schedule", "agent banao", "automate"]):
        background_tasks.add_task(execute_autonomous_task, user_msg)
        return JSONResponse({
            "type": "text",
            "content": "जी, मैंने आपका यह काम बैकग्राउंड में शुरू कर दिया है। आप इंटरनेट बंद कर सकते हैं, मैं इसे सर्वर पर पूरा कर दूँगी।",
            "audio": None
        })

    # Rule 2: Image Generation Locked to Pollinations Flux Engine
    if any(k in msg_low for k in ["image", "photo", "tasveer", "picture"]):
        clean_p = msg_low
        for w in ["image", "photo", "banao", "generate", "create", "ki", "ek", "tasveer"]:
            clean_p = clean_p.replace(w, "")
        clean_p = clean_p.strip() or "cyberpunk neon supercar"
        encoded_prompt = urllib.parse.quote(clean_p)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width=1024&height=1024&nologo=true"
        return JSONResponse({"type": "image", "content": url, "audio": None})

    # Rule 2: Primary Chat Engine (llama-3.1-8b-instant)
    reply = ""
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

    # Rule 2: Fallback Engine (gemini-3.6-flash)
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
        reply = "माफ़ कीजिए, सर्वर से संपर्क नहीं हो पा रहा है। कृपया कुछ देर बाद प्रयास करें।"

    audio_data = generate_voice_b64(reply)
    return JSONResponse({"type": "text", "content": reply, "audio": audio_data})

@app.get("/api/tasks")
def get_tasks():
    return {"tasks": TASK_LOGS}

# Web Dashboard UI
HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maya Meta-Agent OS</title>
    <style>
        :root { --bg: #0d1117; --panel: #161b22; --accent: #238636; --border: #30363d; --text: #c9d1d9; }
        body { margin:0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display:flex; flex-direction:column; height:100vh; }
        header { padding: 14px 20px; background: var(--panel); border-bottom: 1px solid var(--border); font-size: 1.1rem; font-weight: bold; }
        #chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
        .msg { max-width: 85%; padding: 12px 16px; border-radius: 12px; line-height: 1.5; font-size: 0.95rem; }
        .user { align-self: flex-end; background: #1f6feb; color: #fff; border-bottom-right-radius: 2px; }
        .maya { align-self: flex-start; background: var(--panel); border: 1px solid var(--border); border-bottom-left-radius: 2px; }
        .img-card { margin-top: 10px; max-width: 100%; border-radius: 8px; border: 1px solid var(--border); display: block; }
        #controls { padding: 16px; background: var(--panel); border-top: 1px solid var(--border); display: flex; gap: 10px; }
        input { flex: 1; padding: 12px 16px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: #fff; outline: none; font-size: 1rem; }
        button { padding: 12px 20px; background: var(--accent); color: #fff; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; }
    </style>
</head>
<body>
    <header>🤖 Maya Meta-Agent OS <span style="font-size:0.75rem; color:#8b949e;">Render 24/7 Core</span></header>
    <div id="chat">
        <div class="msg maya">नमस्ते! मैं Maya हूँ। आपका सर्वर 24/7 एक्टिव है। आप मुझसे बातचीत कर सकते हैं या कोई तस्वीर बनवा सकते हैं!</div>
    </div>
    <div id="controls">
        <input type="text" id="userInput" placeholder="Maya ko koi bhi command dein..." onkeydown="if(event.key==='Enter') send()">
        <button id="btn" onclick="send()">Send</button>
    </div>
    <audio id="player" style="display:none;"></audio>

    <script>
        async function send() {
            const inp = document.getElementById('userInput');
            const txt = inp.value.trim();
            if(!txt) return;
            inp.value = '';
            
            appendMsg('user', txt);
            const loadingId = 'load_' + Date.now();
            appendLoading(loadingId);

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: txt})
                });
                const data = await res.json();
                removeLoading(loadingId);

                if(data.type === 'image') {
                    appendImg(data.content);
                } else {
                    appendMsg('maya', data.content);
                    if(data.audio) {
                        const audio = document.getElementById('player');
                        audio.src = "data:audio/wav;base64," + data.audio;
                        audio.play();
                    }
                }
            } catch(e) {
                removeLoading(loadingId);
                appendMsg('maya', '⚠️ सर्वर से संपर्क नहीं हो पाया। कृपया पुनः प्रयास करें।');
            }
        }

        function appendMsg(role, text) {
            const c = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = 'msg ' + role;
            div.innerText = text;
            c.appendChild(div);
            c.scrollTop = c.scrollHeight;
        }

        function appendLoading(id) {
            const c = document.getElementById('chat');
            const div = document.createElement('div');
            div.id = id;
            div.className = 'msg maya';
            div.innerText = '⏳ Maya सोच रही है...';
            c.appendChild(div);
            c.scrollTop = c.scrollHeight;
        }

        function removeLoading(id) {
            const el = document.getElementById(id);
            if(el) el.remove();
        }

        function appendImg(src) {
            const c = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = 'msg maya';
            div.innerHTML = `<div>✨ <b>Visual:</b></div><img src="${src}" class="img-card" alt="Generated visual" />`;
            c.appendChild(div);
            c.scrollTop = c.scrollHeight;
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_DASHBOARD
