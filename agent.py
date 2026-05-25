import asyncio
import json
import os
import sys
import urllib.request
import urllib.parse
import websockets

# Reconfigure stdout to use UTF-8 to prevent any console encoding errors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Import OS control functions from core
try:
    from core.system_agent import (
        get_system_stats, open_application, run_command, list_directory, get_time
    )
except ImportError:
    print("Error: Could not import core/system_agent.py. Make sure you are running agent.py from the project folder.")
    sys.exit(1)

CONFIG_FILE = "agent_config.json"

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_config(data: dict):
    config = load_config()
    config.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def get_auth_token(server_url: str, user_name: str, api_key: str) -> str:
    """Make HTTP request to /api/auth to authenticate and get JWT token."""
    clean_url = server_url.rstrip("/")
    auth_url = f"{clean_url}/api/auth"
    payload = json.dumps({"key": api_key, "name": user_name}).encode("utf-8")
    
    req = urllib.request.Request(
        auth_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "JarvisLocalAgent/1.0"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if res_data.get("success"):
                return res_data.get("token")
            else:
                raise Exception(res_data.get("error", "Unknown auth failure."))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            msg = err_body.get("error", e.reason)
        except Exception:
            msg = e.reason
        raise Exception(f"HTTP {e.code}: {msg}")
    except Exception as e:
        raise Exception(f"Failed to connect to auth server: {e}")

async def run_action(action: str, params: dict) -> dict:
    """Execute the target OS control action on this local PC."""
    print(f"🔧 Executing local command: {action} with params {params}")
    try:
        # Dispatch matching actions
        if action == "get_system_stats":
            # Run in executor to avoid blocking the event loop
            return await asyncio.to_thread(get_system_stats)
        elif action == "open_application":
            return await asyncio.to_thread(open_application, params.get("app", ""))
        elif action == "run_command":
            cmd = params.get("command") or params.get("cmd") or ""
            return await asyncio.to_thread(run_command, cmd)
        elif action == "list_directory":
            return await asyncio.to_thread(list_directory, params.get("path", "Desktop"))
        elif action == "get_time":
            return await asyncio.to_thread(get_time)
        else:
            return {"success": False, "error": f"Action '{action}' is not supported by local agent."}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def agent_loop():
    config = load_config()
    server_url = config.get("server_url", "").strip()
    token = config.get("token", "").strip()
    user_name = config.get("user_name", "").strip()

    if not server_url or not token:
        print("╔══════════════════════════════════════════════════╗")
        print("║          J.A.R.V.I.S. LOCAL AGENT SETUP          ║")
        print("╚══════════════════════════════════════════════════╝")
        
        server_url = input("Enter J.A.R.V.I.S. Cloud URL (e.g. http://localhost:8000): ").strip()
        if not server_url:
            server_url = "http://localhost:8000"
            
        user_name = input("Enter your Username (must match HUD profile): ").strip()
        api_key = input("Enter your Groq API Key: ").strip()
        
        print("\n🔑 Authenticating with J.A.R.V.I.S. server...")
        try:
            token = get_auth_token(server_url, user_name, api_key)
            save_config({"server_url": server_url, "token": token, "user_name": user_name})
            print("✅ Authentication successful! Settings saved to agent_config.json.\n")
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            return

    # Convert HTTP/HTTPS URL to WS/WSS
    parsed = urllib.parse.urlparse(server_url)
    ws_scheme = "wss" if parsed.scheme in ["https", "wss"] else "ws"
    netloc = parsed.netloc or parsed.path # path can contain the host if scheme was missing
    ws_url = f"{ws_scheme}://{netloc}/ws_agent"

    print(f"📡 Connecting to J.A.R.V.I.S. cloud at {ws_url}...")
    
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as websocket:
                # 1. Initialize connection
                await websocket.send(json.dumps({
                    "type": "init_agent",
                    "token": token
                }))
                
                # 2. Main message loop
                async for message in websocket:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "init_ok":
                        print(f"✅ J.A.R.V.I.S. Agent connected and authorized for user '{user_name}'!")
                        
                    elif msg_type == "init_fail":
                        print(f"❌ Session authorization failed: {data.get('message')}")
                        # Clear token so user is re-prompted next time
                        save_config({"token": ""})
                        return
                        
                    elif msg_type == "execute":
                        action_id = data.get("action_id")
                        action = data.get("action")
                        params = data.get("params", {})
                        
                        # Execute and send back
                        result = await run_action(action, params)
                        await websocket.send(json.dumps({
                            "type": "action_result",
                            "action_id": action_id,
                            "result": result
                        }))
                        print(f"✅ Command executed and result sent back.")
                        
        except (websockets.exceptions.ConnectionClosed, Exception) as e:
            print(f"⚠️ Connection dropped: {e}")
            print("🔄 Attempting to reconnect in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(agent_loop())
    except KeyboardInterrupt:
        print("\n👋 J.A.R.V.I.S. Agent shutting down. Goodbye, Sir.")
