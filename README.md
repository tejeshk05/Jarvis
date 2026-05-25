<div align="center">

# J.A.R.V.I.S.
### Just A Rather Very Intelligent System

**A personal AI assistant with a cinematic HUD, real-time voice, and proactive system monitoring.**

![Python](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-WebSocket-green?style=flat-square&logo=fastapi)
![MongoDB](https://img.shields.io/badge/MongoDB-Motor-brightgreen?style=flat-square&logo=mongodb)
![Groq](https://img.shields.io/badge/Groq-LLaMA_3.3_70B-orange?style=flat-square)

</div>

---

## ✨ Features

- 🎙️ **Voice I/O** — Speak to JARVIS, hear instant streamed responses via Edge-TTS
- 🧠 **Groq AI** — Powered by LLaMA 3.3-70B for fast, intelligent responses
- 💾 **Persistent Memory** — All conversations stored in MongoDB per user
- 🖥️ **Live HUD** — Real-time CPU, RAM, disk, battery and network telemetry
- 🚨 **Proactive Alerts** — JARVIS speaks up automatically when system health is critical
- 🔐 **JWT Security** — Signed session tokens; raw API key never travels over WebSocket
- 🌦️ **Live Weather** — Real-time weather pulled from wttr.in
- 🌐 **Web Search** — Real-time web search + content extraction
- ⚡ **App Control** — Open apps, run PowerShell commands, manage files by voice

---

## 🗂️ Project Structure

```
jarvis/
├── index.html                  ← Cinematic HUD frontend
├── style.css                   ← Dark glassmorphism UI
├── script.js                   ← Frontend logic (JWT, audio streaming, HUD)
├── server.py                   ← FastAPI orchestrator + WebSocket handler
├── requirements.txt            ← Python dependencies
├── start_jarvis.bat            ← One-click Windows launcher
├── jarvis_config.template.json ← Config template (copy to jarvis_config.json)
└── core/
    ├── auth.py                 ← JWT token system
    ├── database.py             ← MongoDB layer (Motor async)
    ├── intelligence.py         ← Groq AI, TTS, action dispatcher
    └── system_agent.py         ← System stats, app control, web search
```

---

## ⚙️ Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | [Download](https://python.org) |
| MongoDB | [Download Community Edition](https://www.mongodb.com/try/download/community) — must be running locally |
| Groq API Key | Free at [console.groq.com](https://console.groq.com) |
| Windows 10/11 | Some features (app control, battery) are Windows-specific |

---

## 🚀 Setup & Run

**1. Clone the repository**
```bash
git clone https://github.com/your-username/jarvis.git
cd jarvis
```

**2. Set up config**
```bash
copy jarvis_config.template.json jarvis_config.json
```
> You don't need to edit it manually — JARVIS will ask for your Groq API key on first launch.

**3. Start MongoDB**
Make sure your local MongoDB service is running:
```bash
# Windows (Services) or:
net start MongoDB
```

**4. Launch JARVIS**
```batch
.\start_jarvis.bat
```
This automatically installs dependencies, frees port 8000, and opens your browser.

---

## 🔐 Security Model

- Your **Groq API key** is stored locally in `jarvis_config.json` (gitignored) — never hardcoded
- After first login, a **signed JWT token** is issued (24hr expiry) — raw key never travels over WebSocket again
- JWT secret is **auto-generated per machine** on first run
- `jarvis_config.json` is listed in `.gitignore` — it will never be committed

---

## 🧩 Architecture

```
Browser (HUD)
    │  WebSocket (binary audio + JSON)
    ▼
server.py  (FastAPI)
    ├── POST /api/auth      ← JWT issuance
    ├── GET  /api/verify    ← Session validation
    ├── GET  /api/weather   ← Live weather
    └── WS   /ws            ← Main conversation channel
         │
    ┌────┴─────────────────────────┐
    │         core/                │
    │  intelligence.py  ←  Groq   │
    │  system_agent.py  ←  OS     │
    │  database.py      ←  Mongo  │
    │  auth.py          ←  JWT    │
    └──────────────────────────────┘
```

---

## 📜 License

MIT — personal and commercial use allowed.

---

<div align="center">
Built by <strong>D. Tejesh Kumar</strong> — Stark Industries, Malibu Primary
</div>
