# Maya Sovereign OS — Architectural Constitution & System Blueprint

## 1. Executive Summary & Philosophy
- **Identity:** Maya is an autonomous, self-evolving, female meta-agent OS operating across real-time Web Voice Call and Telegram channels.
- **Core Directive:** "Brutal Reality Check" — Zero unverified assumptions, production-verified model endpoints only, hardware-level stability, and fail-safe operation on low-bandwidth/unstable mobile networks.
- **Persona Enforcement:** Strictly female Hindi/Hinglish grammar ("करती हूँ", "बताती हूँ", "देखती हूँ"). Male grammatical markers are hard-rejected.

---

## 2. Hardware-Verified Model Registry
Only models with confirmed 100% inference success on verified API credentials are permitted:

| Role | Provider | Model ID | Token / Rate Threshold | Failure Mode |
| :--- | :--- | :--- | :--- | :--- |
| **Master Router (Fast Brain)** | Groq | `openai/gpt-oss-20b` | Max 70 tokens/call | Fallback to Gemini |
| **Speech-to-Text (STT)** | Groq | `whisper-large-v3-turbo` | 16kHz Mono, Min 7KB chunk | Drop phantom tokens |
| **Hard Fallback & Heavy Brain** | Google Gemini | `gemini-3.6-flash` | v1alpha API | Fail-safe executor |
| **Neural Speech (TTS)** | Azure / Edge | `hi-IN-SwaraNeural` | Single active buffer | Drop older audio buffer |

*Explicit Blacklist:* `llama-3.1-8b-instant`, `llama-3.3-70b-versatile`, `llama3-8b-8192`, `llama3-70b-8192`, `mixtral-8x7b-32768` (Decommissioned / 404 on current tier).

---

## 3. System Architecture & Operational Layers

### Layer 1: Neural Voice Pipeline (Zero Echo & Silent VAD)
- **Input Filtering:** Pure in-memory Web Audio VAD with amplitude threshold > 20. Android system chimes (`webkitSpeechRecognition`) are strictly disabled.
- **Noise Gate:** Rejects audio payloads below 7,000 bytes.
- **Hallucination Shield:** Automatic blocking of phantom tokens produced on room silence (e.g., `'झाल'`, `'subtitles'`, `'thank you'`).
- **Single Channel Lock:** A global session lock (`CURRENT_ACTIVE_WS`) immediately tears down older WebSocket sessions on new client handshake. Live microphone is paused during TTS playback to prevent self-listening loops.

### Layer 2: Fast Master Router (Classification & Guardrails)
- **Decoupling Rule:** Live conversation operates strictly isolated from asynchronous background tasks.
- **Intent Taxonomy:**
  - `chat`: Direct single-sentence voice reply (~150ms latency).
  - `new_heavy_task`: Creates a persistent SQLite record, spawns detached worker, confirms vocally.
  - `modify_task`: Dynamically patches active background tasks mid-execution.
  - `generate_image`: Requires explicit verbal confirmation ("फोटो बनाओ", "image banao").
- **Token Shield:** Output strictly capped at 70 tokens to permanently prevent Groq 429 TPM exhaustion.

### Layer 3: Persistent Storage & Long-Term Memory
- **Database Engine:** SQLite (`maya_jobs.db`) with zero external service dependencies.
- **Schema Contracts:**
  - `tasks`: Job state store (`task_id`, `prompt`, `status`, `modifications`, `result`, `timestamps`).
  - `user_memory`: Key-value knowledge graph (`key`, `value`, `category`, `updated_at`) persisting user instructions, profile constraints, and validated models across container restarts.
- **Crash Recovery:** Server startup scans `tasks` for `pending`/`processing` states and auto-resumes workers without user intervention.

### Layer 4: Autonomous ReAct Engine (Isolated Sandbox)
- **Execution Lifecycle:**
  $$\text{Thought} \longrightarrow \text{Action (Tool Call)} \longrightarrow \text{Observation} \longrightarrow \text{Self-Correction}$$
- **Execution Limits:** Maximum 5 iterative turns per task.
- **Tool Suite:**
  - `web_search`: Live duckduckgo queries.
  - `write_file` / `read_file`: Sandboxed access restricted strictly to `/workspace`.
  - `execute_python`: Subprocess execution with strict 15-second timeout and capture of `stdout`/`stderr`.
- **Model Redundancy:** Executes on `openai/gpt-oss-20b`; transparently falls back to `gemini-3.6-flash` upon connection drops or rate-limit warnings.

### Layer 5: Universal Unified Dispatcher
- **Dual Broadcast:** Worker deliverables dispatch simultaneously to:
  - Active WebSocket client (compact audio/text alert).
  - Telegram Bot (structured report, generated markdown, and physical file attachments from `/workspace`).
- **Conflict Proofing:** Telegram polling wrapped in isolated error handlers (`drop_pending_updates=True`) to prevent instance race conditions and server crash cycles.

---

## 4. Self-Evolution Protocol (Roadmap to Step 6)
- Maya must review its own code via workspace tools, verify execution through isolated Python subprocesses, and inspect exit codes before declaring any software artifact ready.
- Code generation must always include error boundaries, input sanitization, and fallback paths.
