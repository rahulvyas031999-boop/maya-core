# Maya Sovereign OS — Architectural Constitution & System Blueprint
*(Updated after code-vs-blueprint audit — reflects verified, running code)*

## 1. Executive Summary & Philosophy
- **Identity:** Maya is an autonomous, self-evolving, female meta-agent OS operating across real-time Web Voice Call and Telegram channels.
- **Core Directive:** "Brutal Reality Check" — Zero unverified assumptions, production-verified model endpoints only, hardware-level stability, and fail-safe operation on low-bandwidth/unstable mobile networks.
- **Persona Enforcement:** Strictly female Hindi/Hinglish grammar ("करती हूँ", "बताती हूँ", "देखती हूँ"). Male grammatical markers are hard-rejected.

---


## 2. Hardware-Verified Model Registry
Only models with confirmed 100% inference success on verified API credentials are permitted:

| Role | Provider | Model ID | Token / Rate Threshold | Failure Mode |
| :--- | :--- | :--- | :--- | :--- |
| **Master Router (Fast Brain)** | Groq | openai/gpt-oss-20b | Max **300** tokens/call *(raised from 70 — the JSON payload includes task_payload plus several other fields; 70 was truncating responses mid-JSON on longer user messages)* | Fallback to Gemini |
| **Speech-to-Text (STT)** | Groq | whisper-large-v3-turbo | 16kHz Mono, Min 7KB chunk | Drop phantom tokens (blacklist, see Layer 1) |
| **Hard Fallback & Heavy Brain** | Google Gemini | gemini-3.6-flash | v1alpha API | Fail-safe executor |
| **Neural Speech (TTS)** | Azure / Edge | hi-IN-SwaraNeural | Sentence-level streaming queue *(upgraded from single-buffer — sentences are synthesized and sent as soon as ready so playback starts before the full reply is done)* | Per-sentence 10s timeout, skip chunk on failure |

*Explicit Blacklist:* llama-3.1-8b-instant, llama-3.3-70b-versatile, llama3-8b-8192, llama3-70b-8192, mixtral-8x7b-32768 (Decommissioned / 404 on current tier).

*Round-trip timeouts (all `asyncio.wait_for`-wrapped so no call can hang the pipeline):* Router (Groq/Gemini) 10s · Whisper transcription 15s · Per-sentence TTS 10s.

---

## 3. System Architecture & Operational Layers

### Layer 1: Neural Voice Pipeline (Zero Echo & Silent VAD)
- **Input Filtering:** Pure in-memory Web Audio VAD with amplitude threshold > 20. Android system chimes (webkitSpeechRecognition) are strictly disabled.
- **Noise Gate:** Rejects audio payloads below 7,000 bytes (client-side, `templates/index.html`).
- **Hallucination Shield:** `temperature=0.0` + context-priming prompt at the Whisper call, **plus an explicit post-transcription blacklist check** (`is_hallucinated_transcript()` in `main.py`) that discards a transcript when it consists only of a known phantom phrase ("thank you", "subtitles", "झाल", "धन्यवाद", etc.) — exact/near-exact match, not substring, so real sentences containing those words are not wrongly dropped.
- **Single Channel Lock:** A global session lock (`CURRENT_ACTIVE_WS`) now **explicitly calls `await CURRENT_ACTIVE_WS.close()`** on the old socket before a new client handshake replaces the reference — no more zombie connections lingering until they notice on their own. Live microphone is paused during TTS playback to prevent self-listening loops.
- **WS Heartbeat / Idle Detection:** Client ping is answered with pong; if no message (including heartbeat) arrives for 40s, the socket is explicitly closed.

### Layer 2: Fast Master Router (Classification & Guardrails)
- **Decoupling Rule:** Live conversation operates strictly isolated from asynchronous background tasks.
- **Intent Taxonomy:**
  - `chat`: Direct single-sentence voice reply (~150ms latency).
  - `new_heavy_task`: Creates a persistent SQLite record, spawns detached worker, confirms vocally.
  - `modify_task`: Dynamically patches active background tasks mid-execution.
  - `generate_image`: Requires explicit verbal confirmation ("फोटो बनाओ", "image banao").
  - `switch_telegram`: Deterministic keyword fast-path (no LLM round-trip) to fall back to low-bandwidth Telegram mode.
- **Token Shield:** Output capped at **300** tokens (see Section 2 rationale) to balance Groq 429 TPM protection against JSON truncation.
- **Long-Term Memory Context:** Before classification, `recall_memory()` pulls everything Boss has told Maya to remember and injects it into the router prompt as "THINGS YOU ALREADY KNOW ABOUT BOSS," so responses are actually informed by memory, not just storing it unused.

### Layer 3: Persistent Storage & Long-Term Memory
- **Database Engine:** SQLite (`maya_jobs.db`) with zero external service dependencies.
- **Schema Contracts:**
  - `tasks`: Job state store (task_id, prompt, status, modifications, result, timestamps).
  - `user_memory`: Key-value knowledge graph (key, value, category, updated_at) persisting user instructions, profile constraints, and validated models across container restarts.
- **Wiring Status:** `remember_fact()` / `recall_memory()` are now imported and actively used in `main.py` (previously defined but dead code). A deterministic keyword fast-path ("yaad rakhna", "याद रख", "remember this", "from now on") saves the instruction immediately without waiting on an LLM classification.
- **Crash Recovery:** Server startup scans tasks for pending/processing states and auto-resumes workers without user intervention.

### Layer 4: Autonomous ReAct Engine (Isolated Sandbox)
- **Execution Lifecycle:**
  $$\text{Thought} \longrightarrow \text{Action (Tool Call)} \longrightarrow \text{Observation} \longrightarrow \text{Self-Correction}$$
- **Execution Limits:** Maximum 5 iterative turns per task.
- **Tool Suite:**
  - `web_search`: Live duckduckgo queries.
  - `write_file` / `read_file`: Sandboxed access restricted strictly to `/workspace` (verified path-traversal-proof, including sibling-directory attacks).
  - `execute_python`: Subprocess execution with strict 15-second timeout and capture of stdout/stderr.
- **Model Redundancy:** Executes on openai/gpt-oss-20b; transparently falls back to gemini-3.6-flash upon connection drops or rate-limit warnings.

### Layer 5: Universal Unified Dispatcher
- **Dual Broadcast:** Worker deliverables dispatch simultaneously to:
  - Active WebSocket client (compact audio/text alert).
  - Telegram Bot (structured report, generated markdown, and physical file attachments from `/workspace`).
- **Conflict Proofing:** Telegram polling wrapped in isolated error handlers (`drop_pending_updates=True`) to prevent instance race conditions and server crash cycles.

---

## 4. Self-Evolution Protocol (Roadmap to Step 6)
- Maya must review its own code via workspace tools, verify execution through isolated Python subprocesses, and inspect exit codes before declaring any software artifact ready.
- Code generation must always include error boundaries, input sanitization, and fallback paths.
- Every future feature (YouTube, Instagram, email, etc.) must read/write through Layer 3's `user_memory` so context persists across restarts — this is now structurally possible since memory wiring (Layer 3) is live.

---

## 5. Change Log (this audit)
1. **Memory wiring completed** — `remember_fact` / `recall_memory` imported and connected to `master_router`.
2. **Single Channel Lock hardened** — old WebSocket is now explicitly closed, not just reference-replaced.
3. **Hallucination Shield completed** — explicit blacklist check added after Whisper transcription, on top of the existing temperature=0.0 mitigation.
4. **Token Shield documented** — 70→300 token change in the router call was a deliberate, already-shipped fix (JSON truncation), not a spec violation; this blueprint now reflects the real number.
