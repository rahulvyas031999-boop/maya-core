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

TOOL_DECLARATIONS = [
    {
        "name": "generate_image",
        "description": "Call this tool whenever Boss asks to make, draw, render or generate a photo, image, or visual.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Highly detailed photorealistic English description of the image"
                }
            },
            "required": ["prompt"]
        }
    }
]

SYSTEM_PROMPT = (
    "You are Maya, an ultra-smart, conversational female Meta-Agent AI assistant. "
    "Always address the user with high respect as 'Boss' or 'आप'. "
    "Rule 1: Always converse in natural Hindi/Hinglish using strictly female grammatical inflections ('करती हूँ', 'बता दूँगी', 'समझती हूँ'). "
    "Rule 2: Sound human, lively, and warm—like you are sitting right in front of him. "
    "Rule 3: Whenever Boss asks for an image, photo, or visual, invoke the 'generate_image' tool immediately and tell him politely in voice that you are displaying it on screen."
)

@app.websocket("/ws/live")
async def websocket_live_call(ws: WebSocket):
    await ws.accept()
    if not gemini_client:
        await ws.send_json({"type": "error", "message": "Gemini API Key missing"})
        await ws.close()
        return

    live_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM_PROMPT)]),
        tools=[{"function_declarations": TOOL_DECLARATIONS}]
    )

    try:
        async with gemini_client.aio.live.connect(model="gemini-2.5-flash-native-audio-latest", config=live_config) as session:
            
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
                        elif msg.get("type") == "text":
                            await session.send_realtime_input(text=msg["data"])
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as err:
                    print(f"Receive loop error: {err}")

            async def send_to_user():
                try:
                    async for response in session.receive():
                        server_content = response.server_content
                        if server_content and server_content.model_turn:
                            for part in server_content.model_turn.parts:
                                if hasattr(part, "inline_data") and part.inline_data:
                                    b64_audio = base64.b64encode(part.inline_data.data).decode("utf-8")
                                    await ws.send_json({"type": "audio", "data": b64_audio})

                        tool_call = response.tool_call
                        if tool_call:
                            for call in tool_call.function_calls:
                                if call.name == "generate_image":
                                    prompt = call.args.get("prompt", "cinematic photorealistic 8k")
                                    encoded = urllib.parse.quote(prompt)
                                    img_url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
                                    
                                    await ws.send_json({"type": "image", "url": img_url, "prompt": prompt})
                                    
                                    await session.send_tool_response(
                                        function_responses=[
                                            types.FunctionResponse(
                                                id=call.id,
                                                name=call.name,
                                                response={"result": "Image generated and displayed on screen."}
                                            )
                                        ]
                                    )
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as err:
                    print(f"Send loop error: {err}")

            t1 = asyncio.create_task(receive_from_user())
            t2 = asyncio.create_task(send_to_user())
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

    except Exception as e:
        print(f"Live Session Error: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Maya Meta-Agent OS Live</title>
    <style>
        :root { --bg: #07090e; --accent: #00f2fe; --glow: #4facfe; --red: #ff4b2b; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: var(--bg); color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; height: 100dvh; display: flex; flex-direction: column; align-items: center; justify-content: space-between; padding: 24px 16px; overflow: hidden; }
        header { font-size: 1.1rem; font-weight: 700; letter-spacing: 1px; color: #8fa0bc; }
        
        #auraContainer { position: relative; width: 220px; height: 220px; display: flex; align-items: center; justify-content: center; margin-top: 20px; }
        .orb { width: 140px; height: 140px; border-radius: 50%; background: radial-gradient(circle, var(--accent), var(--glow)); box-shadow: 0 0 50px rgba(0, 242, 254, 0.4); transition: transform 0.15s ease, box-shadow 0.15s ease; }
        .orb.speaking { animation: pulseSpeaking 1.2s infinite ease-in-out; }
        .orb.user-active { transform: scale(1.22); box-shadow: 0 0 85px rgba(0, 242, 254, 0.9); }
        @keyframes pulseSpeaking { 0%, 100% { transform: scale(1); box-shadow: 0 0 40px rgba(79, 172, 254, 0.5); } 50% { transform: scale(1.25); box-shadow: 0 0 95px rgba(0, 242, 254, 0.95); } }

        #actionCard { width: 100%; max-width: 380px; min-height: 120px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 12px; display: none; flex-direction: column; align-items: center; gap: 10px; margin-bottom: 10px; }
        #actionCard img { width: 100%; border-radius: 12px; max-height: 240px; object-fit: cover; }
        .download-btn { background: #1f293d; color: #58a6ff; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-size: 0.88rem; font-weight: bold; border: 1px solid rgba(255,255,255,0.15); }

        #controls { display: flex; flex-direction: column; align-items: center; gap: 12px; width: 100%; flex-shrink: 0; }
        #callToggle { width: 72px; height: 72px; border-radius: 50%; background: #238636; border: none; color: #fff; font-size: 1.8rem; cursor: pointer; box-shadow: 0 8px 24px rgba(35, 134, 54, 0.4); display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
        #callToggle.active { background: var(--red); box-shadow: 0 8px 24px rgba(255, 75, 43, 0.5); }
        #statusLabel { font-size: 0.9rem; color: #7d8b99; text-align: center; }
    </style>
</head>
<body>
    <header>MAYA META-AGENT <span style="color:var(--accent);">LIVE OS</span></header>

    <div id="auraContainer">
        <div id="orb" class="orb"></div>
    </div>

    <div id="actionCard">
        <img id="cardImage" src="" />
        <a id="downloadBtn" href="" target="_blank" class="download-btn">⬇️ Download Image</a>
    </div>

    <div id="controls">
        <button id="callToggle" onclick="toggleCall()">📞</button>
        <div id="statusLabel">टैप करें और Maya से बात शुरू करें</div>
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
                // AudioContext initialized upon user touch event
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
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
                    statusLabel.innerText = "Maya सुन रही है Boss...";
                    startMicrophoneStream(micStream);

                    // Send initial handshake trigger so Maya greets first
                    ws.send(JSON.stringify({ type: 'text', data: "नमस्ते Maya! Boss ऑनलाइन आ चुके हैं, उनका अभिवादन कीजिए।" }));
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
                alert("माइक एरर: " + err);
            }
        }

        function stopLiveCall() {
            isCalling = false;
            document.getElementById('callToggle').classList.remove('active');
            document.getElementById('callToggle').innerText = '📞';
            statusLabel.innerText = "कॉल समाप्त। फिर से बात करने के लिए टैप करें।";
            orb.className = 'orb';

            if (processor) processor.disconnect();
            if (micStream) micStream.getTracks().forEach(t => t.stop());
            if (ws && ws.readyState === WebSocket.OPEN) ws.close();
            if (audioCtx && audioCtx.state !== 'closed') audioCtx.close();
        }

        function startMicrophoneStream(stream) {
            const source = audioCtx.createMediaStreamSource(stream);
            processor = audioCtx.createScriptProcessor(4096, 1, 1);
            source.connect(processor);
            processor.connect(audioCtx.destination);

            processor.onaudioprocess = (e) => {
                if (!isCalling || ws.readyState !== WebSocket.OPEN) return;
                const inputData = e.inputBuffer.getChannelData(0);
                
                let sum = 0;
                for (let i = 0; i < inputData.length; i++) sum += inputData[i] * inputData[i];
                let rms = Math.sqrt(sum / inputData.length);
                if (rms > 0.03) {
                    orb.classList.add('user-active');
                } else {
                    orb.classList.remove('user-active');
                }

                // Downsample browser mic buffer to standard 16000Hz PCM
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

            // Gemini Native Audio delivers at 24000Hz
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
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_DASHBOARD
