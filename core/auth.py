"""
core/auth.py — JWT Session Token System
J.A.R.V.I.S. Phase 4: Security & Tokenization

Flow:
  1. User authenticates with Groq API key + name via POST /api/auth
  2. Server issues a signed JWT valid for 24 hours
  3. Frontend stores token in localStorage as 'jarvis_jwt'
  4. Subsequent WS 'init' messages can include the token to skip re-entering the key
  5. Expired or invalid tokens fall back to the API key entry screen
"""

import jwt
import os
import hashlib
from datetime import datetime, timezone, timedelta

# Secret key — in production you'd use a real env variable.
# This is auto-generated per-machine on first use and stored in the config file.
_SECRET_KEY: str | None = None

def get_secret_key() -> str:
    """
    Lazy-load a stable secret key. On first run it is generated from
    machine-specific entropy and stored in jarvis_config.json.
    """
    global _SECRET_KEY
    if _SECRET_KEY:
        return _SECRET_KEY

    from core.database import load_config, save_config
    config = load_config()
    key = config.get("jwt_secret")
    if not key:
        # Generate a stable per-machine secret
        import uuid
        key = hashlib.sha256(str(uuid.getnode()).encode() + b"jarvis-arc-reactor").hexdigest()
        save_config({"jwt_secret": key})
    _SECRET_KEY = key
    return key

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def create_token(user_name: str, api_key: str) -> str:
    """Issue a signed JWT containing the username (not the raw API key)."""
    # Store only last 6 chars of the key as a hint for validation
    key_hint = api_key[-6:] if len(api_key) >= 6 else api_key
    payload = {
        "sub": user_name,
        "key_hint": key_hint,
        "iat": datetime.now(tz=timezone.utc),
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    """
    Verify and decode a JWT.
    Returns the payload dict on success, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
