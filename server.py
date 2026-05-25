"""
J.A.R.V.I.S. — Backend Entry Point (Refactored v2)
Powered by Groq + FastAPI WebSocket

Architecture:
  core/database.py    — MongoDB connection + chat history
  core/system_agent.py — System stats, app control, web search
  core/intelligence.py — Groq AI, TTS, action dispatcher
  server.py           — FastAPI app, HTTP routes, WebSocket handler
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import asyncio
import json
import os
import webbrowser
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ══ Core Modules ══
from core.database import init_db, save_message, load_config, save_config
from core.system_agent import get_system_stats
from core.intelligence import (
    init_groq, generate_speech_base64, stream_speech_chunks,
    extract_json_action, execute_action,
    client, global_user_name, chat_history
)
import core.intelligence as intelligence
from core.auth import create_token, verify_token
from fastapi import Request
from fastapi.responses import JSONResponse

# ══════════════════════════════
#  APP SETUP
# ══════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan: replaces deprecated on_event('startup')."""
    await init_db()
    asyncio.create_task(stats_broadcast_loop())
    asyncio.create_task(proactive_monitor_loop())
    print("🤖 Proactive agent monitor armed.")
    yield  # Server runs here
    # (shutdown cleanup can go here if needed)

app = FastAPI(title="J.A.R.V.I.S.", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def force_utf8_html(request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type") == "text/html":
        response.headers["content-type"] = "text/html; charset=utf-8"
    return response

# Serve static files (the HUD)
app.mount("/static", StaticFiles(directory=os.path.dirname(__file__), html=True), name="static")

# ── Weather API ──
@app.get("/api/weather")
def backend_weather(location: str = None):
    import urllib.request, urllib.parse, json
    try:
        config = load_config()
        loc = location or config.get("weather_location", "")
        loc = loc.strip() if loc else ""

        if loc:
            w_url = f"https://wttr.in/{urllib.parse.quote(loc)}?format=j1"
            w_req = urllib.request.Request(w_url, headers={'User-Agent': 'Mozilla/5.0'})
            w_data = json.loads(urllib.request.urlopen(w_req, timeout=5).read().decode())
            try:
                area = w_data['nearest_area'][0]
                city = area['areaName'][0]['value']
                country = area['country'][0]['value']
                lat = area['latitude']
                lon = area['longitude']
            except Exception:
                city = loc
                country = ""
                lat = "0"
                lon = "0"
        else:
            req = urllib.request.Request('https://freeipapi.com/api/json', headers={'User-Agent': 'Mozilla/5.0'})
            loc_data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            lat = loc_data.get('latitude')
            lon = loc_data.get('longitude')
            city = loc_data.get('cityName', 'Unknown')
            country = loc_data.get('countryCode', 'Unknown')

            w_url = f"https://wttr.in/{lat},{lon}?format=j1"
            w_req = urllib.request.Request(w_url, headers={'User-Agent': 'Mozilla/5.0'})
            w_data = json.loads(urllib.request.urlopen(w_req, timeout=5).read().decode())

        c = w_data['current_condition'][0]
        desc = c.get('weatherDesc', [{'value': 'Unknown'}])[0]['value']

        wmo = 0
        dl = desc.lower()
        if 'cloud' in dl: wmo = 2
        elif 'overcast' in dl: wmo = 3
        elif 'fog' in dl or 'mist' in dl: wmo = 45
        elif 'drizzle' in dl: wmo = 53
        elif 'rain' in dl: wmo = 63
        elif 'snow' in dl: wmo = 73
        elif 'thunder' in dl or 'storm' in dl: wmo = 95

        return {
            "success": True, "city": city, "country": country,
            "lat": lat, "lon": lon, "weathercode": wmo,
            "temperature": float(c.get('temp_C', 0)),
            "windspeed": float(c.get('windspeedKmph', 0)),
            "humidity": float(c.get('humidity', 0))
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════
#  JWT AUTH ENDPOINTS
# ══════════════════════════════
@app.post("/api/auth")
async def api_auth(request: Request):
    """Validate API key + name, then issue a signed JWT session token."""
    try:
        body = await request.json()
        api_key = body.get("key", "").strip()
        name = body.get("name", "Sir").strip() or "Sir"

        success, resolved_name, status, *rest = await init_groq(api_key, name)
        if not success:
            msg = {"IDENTITY_MISMATCH": "IDENTITY MISMATCH! KEY BELONGS TO ANOTHER USER.",
                   "NAME_TAKEN": "NAME TAKEN! CHOOSE A DIFFERENT ALIAS."}.get(status, "Invalid API key.")
            return JSONResponse({"success": False, "error": msg, "status": status}, status_code=401)

        save_config({"groq_key": api_key, "user_name": resolved_name})
        token = create_token(resolved_name, api_key)
        response = JSONResponse({"success": True, "user_name": resolved_name, "token": token})
        # Also set as httpOnly cookie so it survives without localStorage
        response.set_cookie("jarvis_jwt", token, httponly=True, samesite="lax", max_age=86400)
        return response
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.get("/api/verify")
async def api_verify(request: Request):
    """Verify a JWT token. Used on page load to auto-resume sessions."""
    token = request.query_params.get("token") or request.cookies.get("jarvis_jwt", "")
    if not token:
        return JSONResponse({"valid": False, "reason": "no_token"}, status_code=401)
    payload = verify_token(token)
    if not payload:
        return JSONResponse({"valid": False, "reason": "expired_or_invalid"}, status_code=401)
    # Check this user still exists in MongoDB
    import core.database as _dbm
    user = None
    if _dbm.db is not None:
        user = await _dbm.db.users.find_one({"user_name": payload["sub"]})
    return JSONResponse({"valid": True, "user_name": payload["sub"], "groq_key": user.get("api_key", "") if user else ""})

@app.get("/api/agent_status")
async def api_agent_status(request: Request):
    """Check if a local PC agent is connected for the authenticated user."""
    token = request.query_params.get("token") or request.cookies.get("jarvis_jwt", "")
    if not token:
        return JSONResponse({"connected": False, "reason": "unauthenticated"})
    payload = verify_token(token)
    if not payload:
        return JSONResponse({"connected": False, "reason": "invalid_token"})
    user_name = payload.get("sub")
    # connected_agents is a module-level dict defined after this function;
    # access it at call time via the module's global namespace.
    agents = globals().get("connected_agents", {})
    is_connected = user_name in agents
    return JSONResponse({"connected": is_connected, "user_name": user_name})


# ══════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════
connected_clients: set = set()
websocket_states: dict = {}   # websocket -> {"user_name": str, "client": AsyncOpenAI, "chat_history": list}
connected_agents: dict = {}   # user_name -> WebSocket
pending_actions: dict = {}    # action_id -> asyncio.Future


# ══════════════════════════════
#  AGENT HELPER FUNCTIONS
# ══════════════════════════════
async def execute_remote_action(agent_ws, action: str, params: dict) -> dict:
    import uuid
    action_id = str(uuid.uuid4())
    future = asyncio.get_running_loop().create_future()
    pending_actions[action_id] = future
    
    try:
        await agent_ws.send_text(json.dumps({
            "type": "execute",
            "action_id": action_id,
            "action": action,
            "params": params
        }))
        # Wait up to 15 seconds for the local agent to respond
        return await asyncio.wait_for(future, timeout=15.0)
    except asyncio.TimeoutError:
        return {"success": False, "error": "Remote command execution timed out on the client PC, Sir."}
    except Exception as e:
        return {"success": False, "error": f"Remote command execution failed: {e}"}
    finally:
        pending_actions.pop(action_id, None)

async def run_system_action(user_name: str, action: str, params: dict) -> dict:
    # If a remote agent is connected for this user, run it there; otherwise fallback to local server
    agent_ws = connected_agents.get(user_name)
    if agent_ws:
        return await execute_remote_action(agent_ws, action, params)
    else:
        return execute_action(action, params)


# ══════════════════════════════
#  GREETING GENERATOR
# ══════════════════════════════
async def generate_initial_greeting(websocket: WebSocket, user_name: str, user_client, user_chat_history: list, has_history: bool):
    """Generates a dynamic startup greeting via Groq for a specific connection."""
    if has_history:
        prompt = ("The user has just reconnected to the system. Formulate a 1 to 2 sentence greeting "
                  "that explicitly starts with exactly: 'Welcome back, Sir.' "
                  "Infuse a dry, witty British sense of humor regarding whatever you were last discussing "
                  "in the retrieved memory to show continuation.")
    else:
        prompt = ("This is a brand new user. Formulate a 2 to 3 sentence greeting starting with 'Greetings, Sir.' "
                  "Introduce yourself as J.A.R.V.I.S., the highly intelligent neural system created by D. Tejesh Kumar. "
                  "Briefly mention that you can analyze systems, execute terminal commands, and search the live web. "
                  "Keep a professional but subtly witty British tone.")

    try:
        temp_history = user_chat_history.copy()
        temp_history.append({"role": "system", "content": prompt})

        response = await user_client.chat.completions.create(
            model=intelligence.current_model,
            messages=temp_history,
            temperature=0.7,
            max_tokens=150
        )
        reply = response.choices[0].message.content.strip()

        user_chat_history.append({"role": "assistant", "content": reply})
        await save_message("assistant", reply, user_name)

        # Stream audio as binary chunks for instant playback
        await websocket.send_text(json.dumps({
            "type": "response", "text": reply,
            "action_result": None, "tag": "sys",
            "audio_base64": None, "should_speak": False,
            "audio_streaming": True
        }))
        try:
            async for chunk in stream_speech_chunks(reply):
                await websocket.send_bytes(chunk)
            await websocket.send_text(json.dumps({"type": "audio_done"}))
        except Exception:
            await websocket.send_text(json.dumps({"type": "audio_done"}))
    except Exception as e:
        print(f"Failed to generate greeting: {e}")


# ══════════════════════════════
#  WEBSOCKET HANDLER (HUD)
# ══════════════════════════════
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    websocket_states[websocket] = {
        "user_name": "Sir",
        "client": None,
        "chat_history": []
    }
    print("✅ J.A.R.V.I.S. client connected.")

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")
            state = websocket_states.get(websocket)
            if not state:
                continue

            # ── Init (legacy — raw key, kept for backward compat) ──
            if msg_type == "init":
                api_key = data.get("key", "").strip()
                name = data.get("name", "Sir").strip() or "Sir"
                success, resolved_name, status, test_client, c_history = await init_groq(api_key, name)
                if success:
                    save_config({"groq_key": api_key, "user_name": resolved_name})
                    state["user_name"] = resolved_name
                    state["client"] = test_client
                    state["chat_history"] = c_history
                    await websocket.send_text(json.dumps({"type": "init_ok", "message": "Connection established."}))
                    has_user_msgs = any(m.get("role") == "user" for m in c_history)
                    asyncio.create_task(generate_initial_greeting(websocket, resolved_name, test_client, c_history, has_user_msgs))
                else:
                    if status == "IDENTITY_MISMATCH":
                        await websocket.send_text(json.dumps({"type": "init_warning", "message": "IDENTITY MISMATCH! KEY BELONGS TO ANOTHER USER."}))
                    elif status == "NAME_TAKEN":
                        await websocket.send_text(json.dumps({"type": "init_warning", "message": "NAME TAKEN! CHOOSE A DIFFERENT ALIAS."}))
                    else:
                        await websocket.send_text(json.dumps({"type": "init_fail", "message": "Invalid API key, Sir. Please provide a valid Groq API key."}))

            # ══ Init JWT (Phase 4 — secure session resume) ══
            elif msg_type == "init_jwt":
                token = data.get("token", "").strip()
                name = data.get("name", "Sir").strip() or "Sir"
                payload = verify_token(token)
                if not payload:
                    await websocket.send_text(json.dumps({
                        "type": "init_fail",
                        "message": "Session token expired or invalid. Please re-enter your credentials."
                    }))
                    continue
                resolved_name = payload.get("sub", name)
                
                # Fetch key from database instead of shared config file
                import core.database as _dbm
                user = None
                if _dbm.db is not None:
                    user = await _dbm.db.users.find_one({"user_name": resolved_name})
                
                saved_key = user.get("api_key", "") if user else ""
                if not saved_key:
                    await websocket.send_text(json.dumps({"type": "no_saved_key"}))
                    continue
                
                success, r_name, status, test_client, c_history = await init_groq(saved_key, resolved_name)
                if success:
                    state["user_name"] = resolved_name
                    state["client"] = test_client
                    state["chat_history"] = c_history
                    print(f"🔒 JWT session resumed for {resolved_name}")
                    await websocket.send_text(json.dumps({"type": "init_ok", "message": f"Secure session resumed."})) 
                    has_user_msgs = any(m.get("role") == "user" for m in c_history)
                    asyncio.create_task(generate_initial_greeting(websocket, resolved_name, test_client, c_history, has_user_msgs))
                else:
                    await websocket.send_text(json.dumps({"type": "no_saved_key"}))

            # ── Chat ──
            elif msg_type == "message":
                user_client = state["client"]
                user_name = state["user_name"]
                user_chat_history = state["chat_history"]

                if not user_client:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Neural core not initialized. Please enter your Groq API key."}))
                    continue

                user_text = data.get("text", "")
                is_voice = data.get("is_voice", False)
                print(f"USER ({user_name}): {user_text} (Voice: {is_voice})")

                try:
                    import datetime
                    current_time = datetime.datetime.now().strftime("%I:%M %p, %A, %B %d, %Y")
                    full_user_content = f"[System Time: {current_time}]\n{user_text}"

                    user_chat_history.append({"role": "user", "content": full_user_content})
                    await save_message("user", full_user_content, user_name)

                    response = await user_client.chat.completions.create(
                        model=intelligence.current_model,
                        messages=user_chat_history,
                        temperature=0.7
                    )
                    reply = response.choices[0].message.content.strip()
                    print(f"GROQ ({user_name}): {reply[:100]}...")

                    user_chat_history.append({"role": "assistant", "content": reply})
                    await save_message("assistant", reply, user_name)

                    parsed_action, clean_text = extract_json_action(reply)
                    action_result = None

                    if parsed_action:
                        action = parsed_action.get("action")
                        params = parsed_action.get("params", {})
                        message_str = parsed_action.get("message", "")

                        if action == "open_application":
                            action_result = {"success": True, "message": f"Opening {params.get('app', '')}."}
                        else:
                            action_result = await run_system_action(user_name, action, params)

                        reply = clean_text if clean_text else (message_str if message_str else "Executing command, Sir.")

                        if action_result:
                            if "html_override" in action_result:
                                reply += action_result["html_override"]
                            elif "output" in action_result and action_result["output"]:
                                term_out = str(action_result["output"])[:1500]
                                reply += f"<br><br><pre style='color:#00e5ff; font-size:0.85em; background:rgba(0,0,0,0.5); padding:10px; border-left: 2px solid #00e5ff; white-space: pre-wrap; word-wrap: break-word;'>{term_out}</pre>"
                            elif "error" in action_result and action_result["error"]:
                                reply += f"<br><br><pre style='color:#ff1744; font-size:0.85em; background:rgba(0,0,0,0.5); padding:10px; border-left: 2px solid #ff1744; white-space: pre-wrap; word-wrap: break-word;'>{action_result['error']}</pre>"
                            elif action == "get_system_stats":
                                stats_str = "\n".join([f"{k.upper()}: {v}" for k, v in action_result.items()])
                                reply += f"<br><br><pre style='color:#00e5ff; font-size:0.85em; background:rgba(0,0,0,0.5); padding:10px; border-left: 2px solid #00e5ff;'>{stats_str}</pre>"
                    else:
                        reply = clean_text

                    tag_val = "ai"
                    if parsed_action and action_result:
                        tag_val = "search" if parsed_action.get("action") == "search_web" else "sys"

                    audio_b64 = None
                    if is_voice:
                        await websocket.send_text(json.dumps({
                            "type": "response", "text": reply,
                            "action_result": action_result, "tag": tag_val,
                            "audio_base64": None, "should_speak": False,
                            "audio_streaming": True
                        }))
                        try:
                            async for chunk in stream_speech_chunks(reply):
                                await websocket.send_bytes(chunk)
                            await websocket.send_text(json.dumps({"type": "audio_done"}))
                        except Exception as e:
                            print(f"Audio stream error: {e}")
                            await websocket.send_text(json.dumps({"type": "audio_done"}))
                    else:
                        await websocket.send_text(json.dumps({
                            "type": "response", "text": reply,
                            "action_result": action_result, "tag": tag_val,
                            "audio_base64": None, "should_speak": False,
                            "audio_streaming": False
                        }))

                    if parsed_action and parsed_action.get("action") == "open_application":
                        app_name = parsed_action.get("params", {}).get("app", "")
                        delay = min(max(len(reply) * 0.07 if is_voice else 1.0, 1.0), 5.0)
                        async def delayed_open(a, d, u):
                            await asyncio.sleep(d)
                            await run_system_action(u, "open_application", {"app": a})
                        asyncio.create_task(delayed_open(app_name, delay, user_name))

                except Exception as e:
                    err_str = str(e).lower()
                    if "rate_limit" in err_str or "quota" in err_str or "429" in err_str:
                        clean_msg = "My apologies, Sir. Groq Cloud API quotas have been temporarily exhausted. Please wait for the rate limits to reset."
                    elif "authentication" in err_str or "401" in err_str:
                        clean_msg = "Sir, the assigned Groq API key appears to be invalid or previously deactivated."
                    else:
                        clean_msg = f"Neural connection error: {e}"
                    print(f"Chat error: {e}")
                    await websocket.send_text(json.dumps({"type": "error", "message": clean_msg}))

            # ── System Stats ──
            elif msg_type == "get_stats":
                # First check if agent is connected to supply stats; otherwise fallback to local server
                agent_ws = connected_agents.get(state["user_name"])
                if agent_ws:
                    stats = await execute_remote_action(agent_ws, "get_system_stats", {})
                else:
                    stats = get_system_stats()
                await websocket.send_text(json.dumps({"type": "stats", "data": stats}))

            # ── Check Saved Key ──
            elif msg_type == "check_saved_key":
                # Disabled for multi-user security so new browsers always see the authentication screen
                await websocket.send_text(json.dumps({"type": "no_saved_key"}))

            # ── Clear Key ──
            elif msg_type == "clear_key":
                state["client"] = None
                state["chat_history"] = []
                print(f"User {state['user_name']} logged out and state cleared.")

    except WebSocketDisconnect:
        connected_clients.discard(websocket)
        websocket_states.pop(websocket, None)
        print("❌ Client disconnected.")


# ══════════════════════════════
#  WEBSOCKET HANDLER (LOCAL AGENT)
# ══════════════════════════════
@app.websocket("/ws_agent")
async def ws_agent_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🤖 J.A.R.V.I.S. local agent connecting...")
    agent_user_name = None
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "init_agent":
                token = data.get("token", "").strip()
                payload = verify_token(token)
                if not payload:
                    await websocket.send_text(json.dumps({
                        "type": "init_fail",
                        "message": "Session token expired or invalid."
                    }))
                    break
                
                agent_user_name = payload.get("sub")
                connected_agents[agent_user_name] = websocket
                print(f"🔒 Agent authorized and connected for user: {agent_user_name}")
                await websocket.send_text(json.dumps({"type": "init_ok", "message": "Agent connection authorized."}))

            elif msg_type == "action_result":
                action_id = data.get("action_id")
                result = data.get("result")
                future = pending_actions.get(action_id)
                if future and not future.done():
                    future.set_result(result)

    except WebSocketDisconnect:
        print(f"❌ Agent disconnected for user: {agent_user_name}")
    finally:
        if agent_user_name:
            connected_agents.pop(agent_user_name, None)


# ══════════════════════════════
#  BACKGROUND STATS BROADCAST
# ══════════════════════════════
async def stats_broadcast_loop():
    """Push real system stats to all connected clients every 2s."""
    while True:
        await asyncio.sleep(2)
        if connected_clients:
            try:
                s = get_system_stats()
                payload = json.dumps({"type": "stats", "data": s})
                dead = set()
                for ws in connected_clients:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.add(ws)
                connected_clients.difference_update(dead)
                for d in dead:
                    websocket_states.pop(d, None)
            except Exception as e:
                print(f"Stats broadcast error: {e}")


# ══════════════════════════════
#  PROACTIVE AGENT MONITOR (Phase 3)
# ══════════════════════════════
_alert_cooldowns: dict = {}
COOLDOWN_SECONDS = 300  # 5 minutes between same alert type

def _cooldown_ok(key: str) -> bool:
    return (time.time() - _alert_cooldowns.get(key, 0)) > COOLDOWN_SECONDS

async def _send_proactive_alert(alert_type: str, context: str):
    """Generate an AI-voiced proactive alert and push to all connected clients."""
    if not connected_clients:
        return
        
    active_client = None
    for ws in connected_clients:
        st = websocket_states.get(ws)
        if st and st["client"]:
            active_client = st["client"]
            break
            
    if not active_client:
        return

    try:
        prompt = (
            f"Generate a single urgent, concise J.A.R.V.I.S.-style alert (max 18 words) about: {context}. "
            "Always start with 'Sir,' and sound calm, precise, and professional. No filler words."
        )
        response = await active_client.chat.completions.create(
            model=intelligence.current_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=60
        )
        alert_text = response.choices[0].message.content.strip()
        _alert_cooldowns[alert_type] = time.time()
        print(f"🚨 PROACTIVE [{alert_type.upper()}]: {alert_text}")

        payload = json.dumps({
            "type": "proactive_alert",
            "alert_type": alert_type,
            "text": alert_text
        })
        dead = set()
        for ws in connected_clients:
            try:
                await ws.send_text(payload)
                async for chunk in stream_speech_chunks(alert_text):
                    await ws.send_bytes(chunk)
                await ws.send_text(json.dumps({"type": "audio_done"}))
            except Exception:
                dead.add(ws)
        connected_clients.difference_update(dead)
        for d in dead:
            websocket_states.pop(d, None)
    except Exception as e:
        print(f"Proactive alert error: {e}")

async def proactive_monitor_loop():
    """Background task: monitor system health every 60s and alert proactively."""
    await asyncio.sleep(45)  # Let the server fully settle first
    while True:
        await asyncio.sleep(60)
        
        has_active_client = any(st.get("client") is not None for st in websocket_states.values())
        if not connected_clients or not has_active_client:
            continue
            
        try:
            stats = get_system_stats()

            cpu = float(stats['cpu'].replace('%', ''))
            if cpu > 90 and _cooldown_ok('cpu'):
                await _send_proactive_alert('cpu', f'CPU utilisation critically high at {cpu:.0f} percent')

            ram_pct = float(stats['ram'].split('%')[0])
            if ram_pct > 88 and _cooldown_ok('ram'):
                await _send_proactive_alert('ram', f'RAM consumption reached {ram_pct:.0f} percent, memory pressure critical')

            bat_str = stats.get('battery', '')
            if 'On Battery' in bat_str:
                try:
                    bat_pct = float(bat_str.split('%')[0])
                    if bat_pct < 15 and _cooldown_ok('battery'):
                        await _send_proactive_alert('battery', f'Battery at {bat_pct:.0f} percent draining with no power source')
                except Exception:
                    pass

            disk_pct = float(stats['disk'].split('%')[0])
            if disk_pct > 92 and _cooldown_ok('disk'):
                await _send_proactive_alert('disk', f'Primary disk at {disk_pct:.0f} percent capacity, storage critically low')

        except Exception as e:
            print(f"Monitor loop error: {e}")





# ══════════════════════════════
#  ENTRY POINT
# ══════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  J.A.R.V.I.S. — D.TEJESH KUMAR SYSTEM")
    print("  Backend Server + Groq AI Cloud")
    print("=" * 55)
    print("  Opening browser at http://localhost:8000")
    print("  Press Ctrl+C to shut down")
    print("=" * 55)

    port = int(os.environ.get("PORT", 8000))
    if not os.environ.get("PORT"):
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}/static/index.html")
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
