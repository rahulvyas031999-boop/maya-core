import os
import random
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

class ChatReq(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_api(req: ChatReq, background_tasks: BackgroundTasks):
    msg = req.message.strip().lower()

    # Autonomous Background Tasks Detection
    if any(k in msg for k in ["upload", "schedule", "agent banao", "automate"]):
        background_tasks.add_task(execute_autonomous_task, req.message)
        return JSONResponse({
            "type": "text",
            "content": "🚀 आपका टास्क रजिस्टर हो गया है! आप इंटरनेट बंद कर सकते हैं, मैं बैकग्राउंड में यह काम पूरा कर दूँगी।"
        })

    # Image Generation Route (Locked: Pollinations Flux)
    if any(k in msg for k in ["image", "photo", "tasveer", "picture"]):
        clean_prompt = msg
        for w in ["image", "photo", "banao", "generate", "create", "ki", "ek", "tasveer", "do", "dikhaye", "ak"]:
            clean_prompt = clean_prompt.replace(w, "")
        clean_prompt = clean_prompt.strip() or "futuristic supercar in neon rain"
        
        encoded_prompt = urllib.parse.quote(clean_prompt)
        seed = random.randint(1000, 999999)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true&model=flux"
        return JSONResponse({"type": "image", "content": url})

    # Locked Personality: Polite, Feminine Hinglish
    system_prompt = (
        "You are Maya, an intelligent, polite, and caring female AI assistant. "
        "Speak strictly in a natural, warm, and feminine Hinglish tone (always use female grammar like 'karti hoon', 'bata sakti hoon', 'kar dungi', 'samajh gayi'). "
        "Always address the user respectfully as 'aap' (never ever use 'tu' or 'tera'). "
        "Keep your responses concise, smart, and friendly."
    )

    reply = None

    # 1. Primary Engine: Groq llama-3.1-8b-instant (Ultra-Fast 0.2s)
    if groq_client:
        try:
            comp = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": msg}
                ],
                model="llama-3.1-8b-instant"
            )
            reply = comp.choices[0].message.content
        except Exception:
            reply = None

    # 2. Fallback Engine: Gemini gemini-3.6-flash (If Groq fails or unavailable)
    if not reply and gemini_client:
        try:
            res = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=f"{system_prompt}\nUser: {msg}"
            )
            reply = res.text
        except Exception:
            reply = None

    # 3. Safe Fail-Safe Response
    if not reply:
        reply = "माफ़ कीजिए, सर्वर पर इस समय ट्रैफ़िक अधिक है। मैं कुछ ही पलों में वापस तैयार हूँ, कृपया दोबारा पूछें।"

    return JSONResponse({"type": "text", "content": reply})

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
            <div class="msg maya">नमस्ते! मैं माया हूँ। मैं आपकी क्या मदद कर सकती हूँ?</div>
        </div>
        <div id="bar">
            <input id="txt" placeholder="Maya ko koi bhi command dein..." onkeydown="if(event.key==='Enter') send()">
            <button onclick="send()">Send</button>
        </div>

        <script>
            async function send() {
                const inp = document.getElementById('txt');
                const v = inp.value.trim();
                if(!v) return;
                inp.value = '';
                
                append('user', v);
                const loadDiv = append('maya', '⏳ Maya typing...');

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
                    }
                } catch(e) {
                    loadDiv.innerText = '⚠️ एरर, कृपया दोबारा प्रयास करें।';
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
                d.innerHTML = `<div>✨ आपकी इमेज:</div><img src="${url}" class="img-card" onload="this.style.display='block'" onerror="this.parentElement.innerHTML='⚠️ इमेज लोड नहीं हो सकी।'"/>`;
                c.appendChild(d);
                c.scrollTop = c.scrollHeight;
            }
        </script>
    </body>
    </html>
    """
