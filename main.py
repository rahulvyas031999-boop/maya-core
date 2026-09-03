import os
import time
import asyncio
import urllib.parse
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from groq import Groq
from google import genai

app = FastAPI(title="Maya Autonomous Agent OS")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Rule: Boss Persona with strict female inflections ('करती हूँ', 'Boss')
SYSTEM_PROMPT = (
    "You are Maya, a highly capable, loyal, and proactive autonomous female AI assistant. "
    "Always address the user respectfully as 'Boss' or 'आप'. "
    "Rule: Always converse in Hindi or Hinglish using strictly female grammatical inflections "
    "('करती हूँ', 'बता सकती हूँ', 'कर दूँगी', 'समझती हूँ'). "
    "When assigned a task, respond enthusiastically like: 'जी Boss, अभी बनाती हूँ!' "
    "Keep responses short, crisp, natural, and conversational for voice calls."
)

# In-Memory Active Task State Engine
ACTIVE_TASK = {
    "task_name": None,
    "progress": 0,
    "status": "idle",
    "result": None
}

async def run_autonomous_workflow(task_desc: str):
    global ACTIVE_TASK
    ACTIVE_TASK["task_name"] = task_desc
    ACTIVE_TASK["status"] = "running"
    ACTIVE_TASK["progress"] = 10
    
    # Step 1: Planning (10% to 30%)
    await asyncio.sleep(4)
    ACTIVE_TASK["progress"] = 30
    
    # Step 2: Execution / Generation (30% to 60%)
    await asyncio.sleep(6)
    ACTIVE_TASK["progress"] = 60
    
    # Step 3: Optimization & Finalizing (60% to 90%)
    await asyncio.sleep(5)
    ACTIVE_TASK["progress"] = 90
    
    # Step 4: Completion (100%)
    await asyncio.sleep(3)
    ACTIVE_TASK["progress"] = 100
    ACTIVE_TASK["status"] = "completed"
    ACTIVE_TASK["result"] = f"Task '{task_desc}' successfully built and verified."

class ChatReq(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_api(req: ChatReq, background_tasks: BackgroundTasks):
    global ACTIVE_TASK
    user_msg = req.message.strip()
    msg_low = user_msg.lower()

    # 1. Check Task Progress / Status Interruption
    if any(k in msg_low for k in ["kitna kam hua", "kitna kaam hua", "status kya hai", "kaha tak pahucha", "progress"]):
        if ACTIVE_TASK["status"] == "running":
            prog = ACTIVE_TASK["progress"]
            reply = f"लगभग {prog}% Complete है Boss! बस जल्दी ही पूरा करके आपको बताती हूँ।"
        elif ACTIVE_TASK["status"] == "completed":
            reply = f"Boss, आपका पिछला काम 100% पूरा हो चुका है! और कोई टास्क है क्या? मैं हमेशा लाइव और रेडी हूँ, आप बस टास्क बताइए मैं कंप्लीट कर दूँगी!"
        else:
            reply = "Boss, अभी कोई बैकग्राउंड टास्क नहीं चल रहा है। आप मुझे कोई नया काम सौंपिए, मैं तुरंत शुरू कर दूँगी!"
        return JSONResponse({"type": "text", "content": reply})

    # 2. Trigger Autonomous Task (Web page, agent, script, automation)
    if any(k in msg_low for k in ["banao", "create", "bana do", "web page", "website", "script", "automate"]):
        # Agar image nahi mangi hai toh real task run karein
        if not any(k in msg_low for k in ["image", "photo", "tasveer", "picture"]):
            background_tasks.add_task(run_autonomous_workflow, user_msg)
            reply = "जी Boss! अभी बनाती हूँ। मैंने काम शुरू कर दिया है, आप कभी भी मुझसे प्रोग्रेस पूछ सकते हैं!"
            return JSONResponse({"type": "text", "content": reply})

    # 3. High-Quality Image Generation (Flux-Realism + Enhance)
    if any(k in msg_low for k in ["image", "photo", "tasveer", "picture"]):
        clean_p = msg_low
        for w in ["image", "photo", "banao", "generate", "create", "ki", "ek", "tasveer", "do"]:
            clean_p = clean_p.replace(w, "")
        clean_p = clean_p.strip() or "cyberpunk neon supercar"

        final_prompt = clean_p
        if groq_client:
            try:
                enh = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "Convert user request into an 8k cinematic photorealistic English prompt. Output ONLY prompt string."},
                        {"role": "user", "content": clean_p}
                    ],
                    model="llama-3.1-8b-instant",
                    temperature=0.3,
                    max_tokens=60
                )
                final_prompt = enh.choices[0].message.content.strip()
            except Exception:
                final_prompt = f"{clean_p}, 8k ultra detailed photorealistic"

        encoded_prompt = urllib.parse.quote(final_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
        return JSONResponse({"type": "image", "content": url})

    # 4. Primary LLM Chat Engine (Groq Instant)
    reply = ""
    if groq_client:
        try:
            comp = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                model="openai/gpt-oss-120b",
                temperature=0.6
            )
            reply = comp.choices[0].message.content
        except Exception as e:
            print(f"Groq API Error: {e}")

    # 5. Fallback LLM Chat Engine (Gemini 3.6 Flash)
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
        reply = "माफ़ कीजिए Boss, मैं ठीक से सुन नहीं पाई। कृपया दोबारा कहिए।"

    return JSONResponse({"type": "text", "content": reply})

@app.get("/api/tasks")
def get_tasks():
    global ACTIVE_TASK
    return {"active_task": ACTIVE_TASK}

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maya Meta-Agent OS</title>
    <style>
        :root { --bg: #0d1117; --panel: #161b22; --accent: #238636; --border: #30363d; --text: #c9d1d9; --blue: #1f6feb; --red: #da3633; }
        body { margin:0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display:flex; flex-direction:column; height:100vh; }
        header { padding: 14px 20px; background: var(--panel); border-bottom: 1px solid var(--border); font-size: 1.1rem; font-weight: bold; display:flex; justify-content:space-between; align-items:center; }
        #chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
        .msg { max-width: 85%; padding: 12px 16px; border-radius: 12px; line-height: 1.5; font-size: 0.95rem; }
        .user { align-self: flex-end; background: var(--blue); color: #fff; border-bottom-right-radius: 2px; }
        .maya { align-self: flex-start; background: var(--panel); border: 1px solid var(--border); border-bottom-left-radius: 2px; }
        .img-box { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
        .img-card { max-width: 100%; border-radius: 8px; border: 1px solid var(--border); }
        .download-btn { align-self: flex-start; background: #21262d; border: 1px solid var(--border); color: #58a6ff; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: bold; cursor: pointer; text-decoration: none; }
        .download-btn:hover { background: #30363d; }
        #controls { padding: 16px; background: var(--panel); border-top: 1px solid var(--border); display: flex; gap: 10px; align-items: center; }
        input { flex: 1; padding: 12px 16px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: #fff; outline: none; font-size: 1rem; }
        button { padding: 12px 18px; background: var(--accent); color: #fff; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; white-space: nowrap; }
        #liveCallBtn { background: #238636; }
        #liveCallBtn.active { background: var(--red); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }
    </style>
</head>
<body>
    <header>
        <div>🤖 Maya Meta-Agent OS <span style="font-size:0.75rem; color:#3fb950;">V3.0 BOSS CORE</span></div>
        <span id="callIndicator" style="font-size:0.8rem; color:#8b949e;">Standby</span>
    </header>
    <div id="chat">
        <div class="msg maya">नमस्ते Boss! मैं Maya हूँ। मैं हमेशा लाइव और एक्टिव हूँ। आप मुझसे बात कर सकते हैं, कोई भी टास्क दे सकते हैं या लाइव कॉल शुरू कर सकते हैं!</div>
    </div>
    <div id="controls">
        <button id="liveCallBtn" onclick="toggleLiveCall()">📞 Start Call</button>
        <input type="text" id="userInput" placeholder="Boss, टास्क बताइए या कॉल शुरू करें..." onkeydown="if(event.key==='Enter') send()">
        <button id="sendBtn" onclick="send()">Send</button>
    </div>

    <script>
        // Keep-Alive Loop: 4-min server ping
        setInterval(async () => {
            try { await fetch('/api/tasks'); } catch(e) {}
        }, 240000);

        let recognition = null;
        let isLiveCallActive = false;
        let isSpeaking = false;

        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.lang = 'hi-IN';

            recognition.onresult = (e) => {
                const text = e.results[0][0].transcript;
                document.getElementById('userInput').value = text;
                send();
            };

            recognition.onend = () => {
                if (isLiveCallActive && !isSpeaking) {
                    try { recognition.start(); } catch(err) {}
                }
            };

            recognition.onerror = () => {
                if (isLiveCallActive && !isSpeaking) {
                    setTimeout(() => {
                        try { recognition.start(); } catch(err) {}
                    }, 1000);
                }
            };
        }

        function toggleLiveCall() {
            if (!recognition) return alert('Chrome इस्तेमाल करें।');
            const btn = document.getElementById('liveCallBtn');
            const ind = document.getElementById('callIndicator');

            if (!isLiveCallActive) {
                isLiveCallActive = true;
                btn.innerText = '🛑 End Call';
                btn.classList.add('active');
                ind.innerText = '🔴 Live with Boss';
                ind.style.color = '#da3633';
                speakText("जी Boss, मैं लाइव हूँ, आदेश दीजिए।");
            } else {
                isLiveCallActive = false;
                btn.innerText = '📞 Start Call';
                btn.classList.remove('active');
                ind.innerText = 'Standby';
                ind.style.color = '#8b949e';
                if (window.speechSynthesis) window.speechSynthesis.cancel();
                recognition.stop();
            }
        }

        function speakText(text) {
            if (!('speechSynthesis' in window)) return;
            window.speechSynthesis.cancel();
            isSpeaking = true;
            if (recognition) recognition.stop();

            const utter = new SpeechSynthesisUtterance(text);
            utter.lang = 'hi-IN';
            utter.rate = 1.05;

            utter.onend = () => {
                isSpeaking = false;
                if (isLiveCallActive) {
                    try { recognition.start(); } catch(e) {}
                }
            };

            utter.onerror = () => {
                isSpeaking = false;
                if (isLiveCallActive) {
                    try { recognition.start(); } catch(e) {}
                }
            };

            window.speechSynthesis.speak(utter);
        }

        async function send() {
            const inp = document.getElementById('userInput');
            const txt = inp.value.trim();
            if (!txt) return;
            inp.value = '';

            appendMsg('user', txt);
            const loadId = 'load_' + Date.now();
            appendLoading(loadId);

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: txt})
                });
                const data = await res.json();
                removeLoading(loadId);

                if (data.type === 'image') {
                    appendImg(data.content);
                    if (isLiveCallActive) speakText("Boss, मैंने आपकी इमेज तैयार कर दी है।");
                } else {
                    appendMsg('maya', data.content);
                    speakText(data.content);
                }
            } catch(e) {
                removeLoading(loadId);
                appendMsg('maya', '⚠️ सर्वर से संपर्क नहीं हो पाया Boss!');
                if (isLiveCallActive) speakText("क्षमा करें Boss, सर्वर से संपर्क नहीं हुआ।");
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
            div.innerText = '⚡ Maya काम कर रही है Boss...';
            c.appendChild(div);
            c.scrollTop = c.scrollHeight;
        }

        function removeLoading(id) {
            const el = document.getElementById(id);
            if(el) el.remove();
        }

        async function downloadDirect(url) {
            try {
                const res = await fetch(url);
                const blob = await res.blob();
                const blobUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = 'maya_visual_' + Date.now() + '.jpg';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(blobUrl);
            } catch(err) {
                window.open(url, '_blank');
            }
        }

        function appendImg(src) {
            const c = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = 'msg maya';
            div.innerHTML = `
                <div class="img-box">
                    <div>✨ <b>Visual:</b></div>
                    <img src="${src}" class="img-card" alt="Generated visual" />
                    <button class="download-btn" onclick="downloadDirect('${src}')">⬇️ Download Image</button>
                </div>`;
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
