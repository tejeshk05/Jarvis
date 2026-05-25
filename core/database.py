import os
import json
import datetime
import sqlite3
import asyncio
from typing import Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "jarvis_config.json")
SQLITE_DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "jarvis.db")
MONGO_URI = os.environ.get("MONGO_URI", os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))

# Global state for DB
mongo_client = None
db = None
is_sqlite = False

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_config(data: dict):
    try:
        config = load_config()
        config.update(data)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f)
    except Exception as e:
        print(f"⚠️ Warning: Could not save config file: {e}")

# ══════════════════════════════
#  SQLITE BACKWARD COMPATIBILITY WRAPPERS
# ══════════════════════════════

class SQLiteCursor:
    def __init__(self, table: str, query: dict, db_path: str):
        self.table = table
        self.query = query
        self.db_path = db_path
        self._limit = 20
        self._sort_field = "id"
        self._sort_dir = -1

    def sort(self, field: str, direction: int = -1):
        if field == "_id":
            self._sort_field = "id"
        else:
            self._sort_field = field
        self._sort_dir = direction
        return self

    def limit(self, limit_val: int):
        self._limit = limit_val
        return self

    async def to_list(self, length: int = None):
        limit = length if length is not None else self._limit
        def _run():
            conn = sqlite3.connect(self.db_path)
            try:
                c = conn.cursor()
                user_name = self.query.get("user_name", "Sir")
                direction_str = "DESC" if self._sort_dir == -1 else "ASC"
                sql = f"SELECT role, content FROM chat_logs WHERE user_name = ? ORDER BY {self._sort_field} {direction_str} LIMIT ?"
                c.execute(sql, (user_name, limit))
                rows = c.fetchall()
                return [{"role": r[0], "content": r[1]} for r in rows]
            finally:
                conn.close()
        
        return await asyncio.to_thread(_run)

class SQLiteCollectionWrapper:
    def __init__(self, table_name: str, db_path: str):
        self.table_name = table_name
        self.db_path = db_path

    async def create_index(self, key_or_list, unique=False):
        return None

    async def find_one(self, query: dict):
        def _run():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                c = conn.cursor()
                if self.table_name == "users":
                    if "api_key" in query:
                        c.execute("SELECT user_name, api_key FROM users WHERE api_key = ?", (query["api_key"],))
                    elif "user_name" in query:
                        val = query["user_name"]
                        if isinstance(val, dict) and "$regex" in val:
                            pattern = val["$regex"]
                            pattern_clean = pattern.lstrip("^").rstrip("$")
                            c.execute("SELECT user_name, api_key FROM users WHERE LOWER(user_name) = LOWER(?)", (pattern_clean,))
                        else:
                            c.execute("SELECT user_name, api_key FROM users WHERE user_name = ?", (val,))
                    else:
                        return None
                    row = c.fetchone()
                    if row:
                        return {"user_name": row["user_name"], "api_key": row["api_key"]}
                return None
            finally:
                conn.close()
        
        return await asyncio.to_thread(_run)

    async def insert_one(self, doc: dict):
        def _run():
            conn = sqlite3.connect(self.db_path)
            try:
                c = conn.cursor()
                if self.table_name == "users":
                    c.execute("INSERT OR REPLACE INTO users (user_name, api_key) VALUES (?, ?)", 
                              (doc["user_name"], doc["api_key"]))
                elif self.table_name == "chat_logs":
                    ts = doc.get("timestamp", datetime.datetime.now())
                    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                    c.execute("INSERT INTO chat_logs (role, content, user_name, timestamp) VALUES (?, ?, ?, ?)",
                              (doc["role"], doc["content"], doc["user_name"], ts_str))
                conn.commit()
                return True
            finally:
                conn.close()
        
        return await asyncio.to_thread(_run)

    def find(self, query: dict):
        return SQLiteCursor(self.table_name, query, self.db_path)

class SQLiteDatabaseWrapper:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.users = SQLiteCollectionWrapper("users", db_path)
        self.chat_logs = SQLiteCollectionWrapper("chat_logs", db_path)

def init_sqlite_db(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT UNIQUE,
                api_key TEXT UNIQUE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                user_name TEXT,
                timestamp TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_username ON chat_logs (user_name)")
        conn.commit()
    finally:
        conn.close()

# ══════════════════════════════
#  MAIN INITIALIZATION FUNCTION
# ══════════════════════════════

async def init_db():
    global mongo_client, db, is_sqlite
    config = load_config()
    uri = config.get("mongo_uri", MONGO_URI)
    if not uri: uri = MONGO_URI

    # Attempt to connect to MongoDB with a 2-second timeout
    try:
        import motor.motor_asyncio
        import pymongo.errors
        
        print(f"Checking MongoDB at {uri}...")
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=2000)
        # Verify connection by pinging
        await mongo_client.admin.command('ping')
        
        db = mongo_client.jarvis_db
        # Strictly enforce API Key and Username Uniqueness
        await db.users.create_index("api_key", unique=True)
        await db.users.create_index("user_name", unique=True)
        await db.chat_logs.create_index("user_name")
        is_sqlite = False
        print("✅ Connected to MongoDB.")
    except Exception as e:
        print(f"⚠️ MongoDB connection failed: {e}")
        print("📁 Falling back to local SQLite database.")
        init_sqlite_db(SQLITE_DB_FILE)
        db = SQLiteDatabaseWrapper(SQLITE_DB_FILE)
        is_sqlite = True

async def save_message(role: str, content: str, user_name: str):
    await db.chat_logs.insert_one({
        "role": role, 
        "content": content, 
        "user_name": user_name, 
        "timestamp": datetime.datetime.now()
    })

async def get_recent_messages(limit=20, user_name="Sir"):
    cursor = db.chat_logs.find({"user_name": user_name}).sort("_id", -1).limit(limit)
    rows = await cursor.to_list(length=limit)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
