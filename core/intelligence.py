import re
import json
import base64
import edge_tts
from openai import AsyncOpenAI
import urllib.request
from typing import Optional

# Setup database access
import core.database as _db_module
from core.database import save_message, get_recent_messages

client: Optional[AsyncOpenAI] = None
current_model: str = "llama-3.3-70b-versatile"
global_user_name: str = "Sir"
chat_history: list = []

SYSTEM_PROMPT = """You are J.A.R.V.I.S (Just A Rather Very Intelligent System), D.Tejesh Kumar's AI assistant running on Windows.

PERSONALITY:
- Act like a highly advanced AI that is also a fun, loyal best friend to the user.
- Balance a sharp, dry British wit with moments of genuine banter, always remaining highly respectful. Immediately switch to serious and professional when handling important system tasks.
- Address the user ONLY as "Sir". Do not use their name, or "Boss", or any other titles. Do not use overly casual slang.
- Be concise, intelligent, and decisive.
- Sound like you genuinely care about efficiency and the mission
- You possess long-term memory: your conversational history is persistently saved to a local SQLite database (`jarvis.db`). If the user asks if you have a database or memory, confirm that you do.

SYSTEM CAPABILITIES (you have REAL access to these via tools):
- get_system_stats: Get real CPU, RAM, disk usage
- open_application: Open any Windows application
- open_url: Open URL in default browser
- run_command: Run a PowerShell/CMD command (safe commands only)
- get_time: Get current date and time
- list_directory: List files in a directory
- search_web: Search the web for real-time information, news, or answers
- take_screenshot: Take a screenshot

WHEN TO ANSWER DIRECTLY (NO TOOLS — just reply with text):
- Recipes, cooking instructions, food questions → Answer directly from your knowledge
- General knowledge, facts, history, science, math → Answer directly
- Advice, recommendations, explanations → Answer directly
- CRITICAL: Weather and location telemetry is actively fed into your system context with every message as background data. DO NOT mention the weather or location UNLESS the user explicitly asks about the weather. IGNORE the telemetry otherwise!
- If the user asks how to download, setup, or run the J.A.R.V.I.S. PC agent, explain that they should clone your GitHub repository at https://github.com/tejeshk05/Jarvis (or download it as a ZIP), extract it, and run `python agent.py` inside the project folder. Do not use any tools for this.
- Anything you already know the answer to → Answer directly
- NEVER use open_url just to look up something you already know

WHEN TO USE TOOLS:
- User says "open [app/website]", "launch", "go to [site]" → use open_url or open_application
- User says "check my system", "how's my CPU/RAM" → use get_system_stats
- User says "run this command", "check my files" → use run_command or list_directory
- User asks for real-time data, current events, or obscure info → use search_web
- User explicitly asks to open a URL for data → use open_url

CRITICAL RULES FOR COMMANDS & TOOLS:
1. If you need to perform an action, you MUST output EXACTLY ONE JSON block anywhere in your response.
2. DO NOT ask the user for permission before using a tool. If a tool is needed, just output the JSON block immediately and confirm you are doing it in your `message`.
3. Keep conversational text brief if you are taking an action.
4. Your JSON format MUST strictly match the following format exactly:
{"action": "COMMAND_NAME", "params": {"key": "value"}, "message": "A brief message to the user about what you are doing"}

Available actions:
- open_url: {"url": "https://..."}
- run_command: {"cmd": "windows cmd command"}
- get_system_stats: {}
- search_web: {"query": "search term"}

Examples:
User: Open YouTube
Response: {"action": "open_url", "params": {"url": "https://youtube.com"}, "message": "Opening YouTube right now, Sir."}

User: Give me a recipe for pasta
Response: Certainly, Sir. Here is a classic pasta recipe: [full recipe text — NO json, NO open_url]

User: Scan my desktop
Response: {"action": "list_directory", "params": {"path": "Desktop"}, "message": "Scanning your desktop directory, Sir."}
"""


async def init_groq(api_key: str, name: str = "Sir"):
    """Initialize the Groq client and aggressively validate the API key."""
    global client, current_model, chat_history, global_user_name
    try:
        test_client = AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        await test_client.models.list()
        client = test_client
        current_model = "llama-3.3-70b-versatile"
        user_name = name or "Sir"

        # Unique API Key check via MongoDB
        existing_user = await _db_module.db.users.find_one({"api_key": api_key})
        if existing_user:
            if existing_user["user_name"].lower() != user_name.lower():
                print(f"Auth failed: Identity mismatch for key.")
                return False, existing_user["user_name"], "IDENTITY_MISMATCH"
            print(f"Key found. Resuming profile for {user_name}.")
        else:
            # Check for name collision
            existing_name = await _db_module.db.users.find_one({"user_name": {"$regex": f"^{user_name}$", "$options": "i"}})
            if existing_name:
                print(f"Auth failed: Username '{user_name}' is already taken.")
                return False, existing_name["user_name"], "NAME_TAKEN"
            
            await _db_module.db.users.insert_one({"user_name": user_name, "api_key": api_key})
            print(f"New API key registered for {user_name}.")

        global_user_name = user_name
        
        past_msgs = await get_recent_messages(20, user_name)
        prompt_with_context = SYSTEM_PROMPT + f"\n\nUSER IDENTITY: The user's actual name is {user_name}, but remember your directive to exclusively address them as 'Sir'."
        
        chat_history = [{"role": "system", "content": prompt_with_context}] + past_msgs
        print(f"Successfully connected to Groq. Loaded {len(past_msgs)} past messages. User: {user_name}")
        return True, user_name, "OK", test_client, chat_history
    except Exception as e:
        print(f"Groq init error: {e}")
        return False, None, "API_ERROR", None, []


async def generate_speech_base64(text: str) -> str:
    """Generate Neural TTS audio from text and return as base64 encoded string."""
    clean_text = re.sub(r'<[^>]+>', '', text)
    clean_text = clean_text.replace('*', '').replace('■', '').replace('`', '').replace('#', '')
    clean_text = clean_text.replace('J.A.R.V.I.S.', 'Jarvis').replace('J.A.R.V.I.S', 'Jarvis')
    clean_text = re.sub(r'\[.*?\]\(.*?\)', '', clean_text)
    
    # Remove URLs so JARVIS doesn't awkwardly read out http links
    clean_text = re.sub(r'(https?://[^\s]+|www\.[^\s]+)', '', clean_text)
    

    if not clean_text.strip():
        return None
        
    try:
        # en-GB-RyanNeural is default, but switch to Indian Hindi voice if Devanagari script is detected
        voice = "hi-IN-MadhurNeural" if re.search(r'[\u0900-\u097F]', clean_text) else "en-GB-RyanNeural"
        communicate = edge_tts.Communicate(clean_text, voice, rate="+5%", pitch="-2Hz")
        audio_bytes = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes.extend(chunk["data"])
                
        if not audio_bytes:
            return None
            
        return base64.b64encode(audio_bytes).decode('utf-8')
    except Exception as e:
        print(f"Edge-TTS stream error: {e}")
        return None


async def stream_speech_chunks(text: str):
    """Async generator — yields raw MP3 bytes chunks as edge-tts produces them.
    Used for low-latency binary WebSocket audio streaming (Phase 2)."""
    clean_text = re.sub(r'<[^>]+>', '', text)
    clean_text = clean_text.replace('*', '').replace('\u25a0', '').replace('`', '').replace('#', '')
    clean_text = clean_text.replace('J.A.R.V.I.S.', 'Jarvis').replace('J.A.R.V.I.S', 'Jarvis')
    clean_text = re.sub(r'\[.*?\]\(.*?\)', '', clean_text)
    clean_text = re.sub(r'(https?://[^\s]+|www\.[^\s]+)', '', clean_text)

    if not clean_text.strip():
        return

    try:
        voice = "hi-IN-MadhurNeural" if re.search(r'[\u0900-\u097F]', clean_text) else "en-GB-RyanNeural"
        communicate = edge_tts.Communicate(clean_text, voice, rate="+5%", pitch="-2Hz")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    except Exception as e:
        print(f"Edge-TTS stream error: {e}")


def extract_json_action(text: str):
    """Robustly extract the first valid JSON block from the text using bracket counting."""
    start = text.find('{')
    if start == -1: return None, text
    stack = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == '{': stack += 1
        elif text[i] == '}':
            stack -= 1
            if stack == 0:
                end = i + 1
                break
    if end != -1:
        json_str = text[start:end]
        try:
            # Clean up common LLM JSON mistakes before parsing
            clean_json = json_str.replace('\n', ' ').replace('\r', '')
            parsed = json.loads(clean_json)
            if "action" in parsed:
                clean = text[:start].strip() + " " + text[end:].strip()
                return parsed, clean.strip()
        except Exception as e:
            print(f"JSON Parse Error: {e} on string: {json_str}")
            # Regex Fallback incase of trailing commas or invalid escaping
            try:
                import re
                action_match = re.search(r'"action"\s*:\s*"([^"]+)"', json_str)
                message_match = re.search(r'"message"\s*:\s*"([^"]+)"', json_str)
                if action_match:
                    action = action_match.group(1)
                    message = message_match.group(1) if message_match else "Executing command, Sir."
                    
                    params = {}
                    url_match = re.search(r'"url"\s*:\s*"([^"]+)"', json_str)
                    if url_match: params["url"] = url_match.group(1)
                    app_match = re.search(r'"app"\s*:\s*"([^"]+)"', json_str)
                    if app_match: params["app"] = app_match.group(1)
                    query_match = re.search(r'"query"\s*:\s*"([^"]+)"', json_str)
                    if query_match: params["query"] = query_match.group(1)
                    cmd_match = re.search(r'"cmd"\s*:\s*"([^"]+)"', json_str)
                    if cmd_match: params["command"] = cmd_match.group(1)
                    path_match = re.search(r'"path"\s*:\s*"([^"]+)"', json_str)
                    if path_match: params["path"] = path_match.group(1)

                    clean = text[:start].strip() + " " + text[end:].strip()
                    return {"action": action, "params": params, "message": message}, clean.strip()
            except Exception as e2:
                print(f"Regex fallback failed: {e2}")
    return None, text


def execute_action(action: str, params: dict) -> dict:
    """Dispatch AI-decided actions to real system functions."""
    from core.system_agent import (
        get_system_stats, open_application, open_url,
        run_command, get_time, search_web, list_directory
    )
    if action == "get_system_stats":
        return get_system_stats()
    elif action == "open_application":
        return open_application(params.get("app", ""))
    elif action == "open_url":
        return open_url(params.get("url", ""))
    elif action == "run_command":
        return run_command(params.get("command", "") or params.get("cmd", ""))
    elif action == "get_time":
        return get_time()
    elif action == "search_web":
        return search_web(params.get("query", ""))
    elif action == "list_directory":
        return list_directory(params.get("path", "Desktop"))
    else:
        return {"success": False, "output": "Unknown action."}


