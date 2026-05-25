import json
import os
import sys

# Reconfigure stdout to use UTF-8 to prevent any console encoding errors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Ensure core imports can be found from the current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.auth import create_token
from core.database import load_config

def main():
    config = load_config()
    api_key = config.get("groq_key", "")
    if not api_key:
        print("Error: No groq_key found in jarvis_config.json.")
        sys.exit(1)
        
    # We use 'Tony' as the user name based on the server logs
    user_name = "Tony"
    token = create_token(user_name, api_key)
    
    agent_config = {
        "server_url": "http://localhost:8000",
        "user_name": user_name,
        "token": token
    }
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_config.json")
    with open(config_path, "w") as f:
        json.dump(agent_config, f, indent=4)
        
    print(f"agent_config.json created successfully at {config_path}")
    print(f"Token: {token[:15]}...{token[-15:]}")

if __name__ == "__main__":
    main()
