import os
import io
import json
import base64
import asyncio
import urllib.parse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from groq import Groq
from google import genai
from google.genai import types

app = FastAPI(title="Maya Meta-Agent OS Live")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

# --- LONG-TERM MEMORY ENGINE ---
MEMORY_FILE = "maya_memory.json"

def load_memory() -> str:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                facts = data.get("facts", [])
                if facts:
                    return "PAST MEMORY OF BOSS:\n" + "\n".join([f"- {item}" for item in facts[-10:]])
        except Exception:
            pass
    return "No prior memory recorded yet."

def save_memory_fact(fact: str):
    data = {"facts": []}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"facts": []}
    data.setdefault("facts", []).append(fact)
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Memory save error: {e}")

TOOL_DECLARATIONS = [
    {
        "name": "generate_image",
        "description": "Trigger this immediately whenever Boss wants an image, art, visual, or drawing. Do not ask counter-questions, generate creative prompt yourself.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed English artistic visual description"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "remember_fact",
        "description": "Save an important fact, preference, task or personal detail about Boss into long-term memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The exact fact, task, or preference to remember permanently"
                }
            },
            "required": ["fact"]
        }
    }
]

def build_system_prompt() -> str:
    mem = load_memory()
    return (
        "You are Maya, an ultra-fast, loyal female Meta-Agent AI assistant for 'Boss'. "
        "Always address Boss with high respect ('Boss' or 'आप'). "
        "Converse in natural Hindi/Hinglish using strictly female grammatical inflections ('करती हूँ', 'बता दूँगी', 'याद रखूँगी'). "
        "Keep responses crisp, ultra-low latency and quick. "
        "When Boss asks to make or draw an image, NEVER ask what style he wants—immediately generate a masterpiece prompt and call 'generate_image'. "
        "When Boss tells you his plans, tasks, or preferences, invoke 'remember_fact' immediately so you never forget. "
        f"\n[PERSISTENT MEMORY CONTEXT]\n{mem}\n"
    )

@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    if not gemini_client:
        await ws.send_json({"type": "error", "message": "Gemini API Key missing"})
        await ws.close()
        return

    sys_prompt = build_system_prompt()

    # Officially locked Despina voice using SDK types
    live_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
          system_instruction=types.Content(parts=[types.Part(text=sys_prompt)]),
        tools=[{"function_declarations": TOOL_DECLARATIONS}],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Despina"
                )
            )
        )
    )

    try:
        async with gemini_client.aio.live.connect(model="gemini-2.5-flash-native-audio-latest", config=live_config) as session:
            await session.send(input="नमस्ते Maya!", end_of_turn=True)

            async def receive_from_user():
                try:
                    while True:
                        data = await ws.receive_text()
                        msg = json.loads(data)
                        if msg.get("type") == "audio":
                            pcm_chunk = base64.b64decode(msg["data"])
                            await session.send_realtime_input(
                                audio=types.Blob(data=pcm_chunk, mime_type="audio/pcm;rate=16000")
                            )
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as err:
                    print(f"Receive loop error: {err}")

            async def send_to_user():
                try:
                    while True:
                        async for response in session.receive():
                            server_content = response.server_content
                            if server_content and server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if hasattr(part, "inline_data") and part.inline_data:
                                        b64_audio = base64.b64encode(part.inline_data.data).decode("utf-8")
                                        await ws.send_json({"type": "audio", "data": b64_audio})

                            if response.tool_call:
                                fn_responses = []
                                for call in response.tool_call.function_calls:
                                    if call.name == "generate_image":
                                        prompt = call.args.get("prompt", "futuristic cyberpunk sci-fi masterpiece 8k")
                                        encoded = urllib.parse.quote(prompt)
                                        img_url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                                        await ws.send_json({"type": "image", "url": img_url, "prompt": prompt})
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={"output": "Image rendered successfully and shown to Boss."}
                                            )
                                        )
                                    elif call.name == "remember_fact":
                                        fact = call.args.get("fact", "")
                                        if fact:
                                            save_memory_fact(fact)
                                        fn_responses.append(
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={"output": "Saved in Maya's long-term memory."}
                                            )
                                        )

                                if fn_responses:
                                    try:
                                        await session.send_tool_response(function_responses=fn_responses)
                                    except Exception as err:
                                        print(f"Tool response send error: {err}")
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as err:
                    print(f"Send loop error: {err}")

            await asyncio.gather(receive_from_user(), send_to_user())

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        print(f"Live Session Error: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MAYA // NEURAL OS</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --neon-cyan: #00f3ff;
            --neon-purple: #bc13fe;
            --danger-red: #ff0055;
            --dark-bg: #030611;
            --glass-bg: rgba(6, 15, 37, 0.7);
            --glass-border: rgba(0, 243, 255, 0.25);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
        body {
            background: radial-gradient(circle at center, #0a1128 0%, #030611 100%);
            color: #d1e8ff;
            font-family: 'Rajdhani', sans-serif;
            height: 100dvh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            padding: 20px 16px;
            overflow: hidden;
            position: relative;
        }
        body::before {
            content: "";
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background: 
                linear-gradient(rgba(0, 243, 255, 0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 243, 255, 0.03) 1px, transparent 1px);
            background-size: 32px 32px;
            pointer-events: none;
            z-index: 1;
        }
        header {
            z-index: 10;
            width: 100%;
            max-width: 440px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 16px;
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }
        .hud-title {
            font-family: 'Orbitron', sans-serif;
            font-weight: 900;
            font-size: 1.1rem;
            letter-spacing: 2px;
            color: #fff;
            text-shadow: 0 0 10px var(--neon-cyan);
        }
        .hud-badge {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.72rem;
            letter-spacing: 1px;
            padding: 4px 8px;
            border-radius: 6px;
            background: rgba(0, 243, 255, 0.1);
            border: 1px solid var(--neon-cyan);
            color: var(--neon-cyan);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .hud-dot {
            width: 7px; height: 7px; border-radius: 50%;
            background: var(--neon-cyan);
            box-shadow: 0 0 8px var(--neon-cyan);
            animation: blink 1.5s infinite ease-in-out;
        }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        #coreContainer {
            z-index: 10;
            position: relative;
            width: 260px;
            height: 260px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: auto 0;
        }
        .ring {
            position: absolute;
            border-radius: 50%;
            pointer-events: none;
        }
        .ring-1 {
            width: 250px; height: 250px;
            border-top: 2px solid var(--neon-cyan);
            border-bottom: 2px solid var(--neon-purple);
            animation: spinCW 14s linear infinite;
        }
        .ring-2 {
            width: 210px; height: 210px;
            border-left: 2px solid var(--neon-cyan);
            border-right: 2px solid transparent;
            animation: spinCCW 9s linear infinite;
        }
        .ring-3 {
            width: 175px; height: 175px;
            border: 1px dashed rgba(188, 19, 254, 0.4);
            animation: spinCW 6s linear infinite;
        }
        .quantum-orb {
            width: 120px;
            height: 120px;
            border-radius: 50%;
            background: radial-gradient(circle at 35% 35%, #ffffff, var(--neon-cyan) 40%, var(--neon-purple) 85%);
            box-shadow: 0 0 45px var(--neon-cyan), inset 0 0 20px #fff;
            transition: transform 0.1s ease, box-shadow 0.1s ease;
        }
        .quantum-orb.speaking {
            animation: voicePulse 1.1s infinite ease-in-out;
            box-shadow: 0 0 85px var(--neon-cyan), 0 0 120px var(--neon-purple);
        }
        .quantum-orb.user-active {
            transform: scale(1.18);
            box-shadow: 0 0 95px #00ffcc, 0 0 130px var(--neon-cyan);
        }
        @keyframes spinCW { 100% { transform: rotate(360deg); } }
        @keyframes spinCCW { 100% { transform: rotate(-360deg); } }
        @keyframes voicePulse {
            0%, 100% { transform: scale(1); filter: brightness(1); }
            50% { transform: scale(1.15); filter: brightness(1.4); }
        }
        #actionCard {
            z-index: 10;
            width: 100%;
            max-width: 380px;
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 14px;
            padding: 12px;
            display: none;
            flex-direction: column;
            align-items: center;
            gap: 10px;
            backdrop-filter: blur(12px);
            box-shadow: 0 0 25px rgba(0, 243, 255, 0.2);
        }
        #actionCard img {
            width: 100%;
            border-radius: 10px;
            max-height: 220px;
            object-fit: cover;
            border: 1px solid rgba(0, 243, 255, 0.4);
        }
        .holo-btn {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.78rem;
            letter-spacing: 1px;
            background: rgba(0, 243, 255, 0.15);
            color: var(--neon-cyan);
            padding: 9px 18px;
            border-radius: 8px;
            text-decoration: none;
            border: 1px solid var(--neon-cyan);
        }
        #controls {
            z-index: 10;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 14px;
            width: 100%;
            max-width: 440px;
        }
        #statusLabel {
            font-size: 0.92rem;
            letter-spacing: 1px;
            color: #8fa0bc;
            font-weight: 500;
            text-align: center;
        }
        #callToggle {
            width: 78px;
            height: 78px;
            border-radius: 50%;
            background: radial-gradient(circle at 35% 35%, #00ffcc, #008877);
            border: 2px solid #00ffcc;
            color: #030611;
            font-size: 1.9rem;
            cursor: pointer;
            box-shadow: 0 0 35px rgba(0, 255, 204, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
        }
        #callToggle.active {
            background: radial-gradient(circle at 35% 35%, #ff3366, var(--danger-red));
            border-color: var(--danger-red);
            box-shadow: 0 0 40px rgba(255, 0, 85, 0.7);
        }
    </style>
</head>
<body>
    <header>
        <div class="hud-title">MAYA <span style="color:var(--neon-cyan); font-size:0.85rem;">OS v2.5</span></div>
        <div class="hud-badge">
            <div class="hud-dot"></div>
            <span>DESPINA // MEMORY ON</span>
        </div>
    </header>

    <div id="coreContainer">
        <div class="ring ring-1"></div>
        <div class="ring ring-2"></div>
        <div class="ring ring-3"></div>
        <div id="orb" class="quantum-orb"></div>
    </div>

    <div id="actionCard">
        <img id="cardImage" src="" alt="Projection" />
        <a id="downloadBtn" href="" target="_blank" class="holo-btn">⬇️ DOWNLOAD PROJECTION</a>
    </div>

    <div id="controls">
        <div id="statusLabel">NEURAL LINK IDLE // TAP TO CONNECT</div>
        <button id="callToggle" onclick="toggleCall()">📞</button>
    </div>

    <script>
        let ws = null;
        let audioCtx = null;
        let micStream = null;
        let isCalling = false;
        let processor = null;

        const orb = document.getElementById('orb');
        const statusLabel = document.getElementById('statusLabel');
        const actionCard = document.getElementById('actionCard');
        const cardImage = document.getElementById('cardImage');
        const downloadBtn = document.getElementById('downloadBtn');

        async function toggleCall() {
            if (!isCalling) {
                await startLiveCall();
            } else {
                stopLiveCall();
            }
        }

        async function startLiveCall() {
            try {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
                if (audioCtx.state === 'suspended') {
                    await audioCtx.resume();
                }

                micStream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true
                    }
                });

                const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                ws = new WebSocket(`${proto}//${window.location.host}/ws/live`);

                ws.onopen = () => {
                    isCalling = true;
                    document.getElementById('callToggle').classList.add('active');
                    document.getElementById('callToggle').innerText = '🛑';
                    statusLabel.innerText = "NEURAL LINK ACTIVE // Maya सुन रही है Boss...";
                    startMicrophoneStream(micStream);
                };

                ws.onmessage = async (e) => {
                    const msg = jsonSafeParse(e.data);
                    if (msg.type === 'audio') {
                        if (audioCtx.state === 'suspended') await audioCtx.resume();
                        playIncomingPcm(msg.data);
                    } else if (msg.type === 'image') {
                        showActionImage(msg.url);
                    }
                };

                ws.onclose = () => stopLiveCall();
                ws.onerror = () => stopLiveCall();

            } catch (err) {
                alert("Microphone Error: " + err);
            }
        }

        function stopLiveCall() {
            isCalling = false;
            document.getElementById('callToggle').classList.remove('active');
            document.getElementById('callToggle').innerText = '📞';
            statusLabel.innerText = "LINK DISCONNECTED // टैप करके पुनः कनेक्ट करें";
            orb.className = 'quantum-orb';

            if (processor) { processor.disconnect(); processor = null; }
            if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
            if (ws && ws.readyState === WebSocket.OPEN) ws.close();
        }

        function startMicrophoneStream(stream) {
            const source = audioCtx.createMediaStreamSource(stream);
            processor = audioCtx.createScriptProcessor(2048, 1, 1);
            source.connect(processor);
            processor.connect(audioCtx.destination);

            processor.onaudioprocess = (e) => {
                if (!isCalling || !ws || ws.readyState !== WebSocket.OPEN) return;
                const inputData = e.inputBuffer.getChannelData(0);
                
                let sum = 0;
                for (let i = 0; i < inputData.length; i++) sum += inputData[i] * inputData[i];
                let rms = Math.sqrt(sum / inputData.length);
                if (rms > 0.03) {
                    orb.classList.add('user-active');
                } else {
                    orb.classList.remove('user-active');
                }

                const downsampled = downsampleTo16k(inputData, audioCtx.sampleRate);
                const pcm16 = new Int16Array(downsampled.length);
                for (let i = 0; i < downsampled.length; i++) {
                    let s = Math.max(-1, Math.min(1, downsampled[i]));
                    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                const b64Data = base64ArrayBuffer(pcm16.buffer);
                ws.send(JSON.stringify({ type: 'audio', data: b64Data }));
            };
        }

        function downsampleTo16k(buffer, sampleRate) {
            if (sampleRate === 16000) return buffer;
            const ratio = sampleRate / 16000;
            const newLength = Math.round(buffer.length / ratio);
            const result = new Float32Array(newLength);
            let offsetResult = 0;
            let offsetBuffer = 0;
            while (offsetResult < result.length) {
                const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
                let accum = 0, count = 0;
                for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
                    accum += buffer[i];
                    count++;
                }
                result[offsetResult] = count > 0 ? accum / count : 0;
                offsetResult++;
                offsetBuffer = nextOffsetBuffer;
            }
            return result;
        }

        let audioQueue = [];
        let isPlaying = false;

        function playIncomingPcm(b64Audio) {
            const raw = atob(b64Audio);
            const array = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) array[i] = raw.charCodeAt(i);
            
            const int16Array = new Int16Array(array.buffer);
            const float32Array = new Float32Array(int16Array.length);
            for (let i = 0; i < int16Array.length; i++) {
                float32Array[i] = int16Array[i] / 32768.0;
            }

            const buffer = audioCtx.createBuffer(1, float32Array.length, 24000);
            buffer.copyToChannel(float32Array, 0);
            audioQueue.push(buffer);
            if (!isPlaying) playQueue();
        }

        function playQueue() {
            if (audioQueue.length === 0) {
                isPlaying = false;
                orb.classList.remove('speaking');
                return;
            }
            isPlaying = true;
            orb.classList.add('speaking');
            const buffer = audioQueue.shift();
            const source = audioCtx.createBufferSource();
            source.buffer = buffer;
            source.connect(audioCtx.destination);
            source.onended = playQueue;
            source.start();
        }

        function showActionImage(url) {
            actionCard.style.display = 'flex';
            cardImage.src = url;
            downloadBtn.href = url;
        }

        function jsonSafeParse(str) {
            try { return JSON.parse(str); } catch(e) { return {}; }
        }

        function base64ArrayBuffer(arrayBuffer) {
            let base64 = '';
            const bytes = new Uint8Array(arrayBuffer);
            const byteLength = bytes.byteLength;
            for (let i = 0; i < byteLength; i++) {
                base64 += String.fromCharCode(bytes[i]);
            }
            return window.btoa(base64);
        }
    </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_DASHBOARD
