import os
import sqlite3
from pathlib import Path
import queue
import http.client

# Global Config
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "conversations.db"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))

# Shared Models
MODELS = {
    "fast": "qwen2.5-coder:1.5b",
    "balanced": "qwen2.5-coder:3b"
}

# Shared Connection Pool logic to avoid "port in use" or "too many connections" errors
class OllamaConnectionPool:
    def __init__(self, host, port, max_size=10):
        self.host = host
        self.port = port
        self.pool = queue.Queue(maxsize=max_size)
    def get_connection(self):
        try: return self.pool.get_nowait()
        except: return http.client.HTTPConnection(self.host, self.port, timeout=90)
    def return_connection(self, conn):
        try: self.pool.put_nowait(conn)
        except: conn.close()

OLLAMA_POOL = OllamaConnectionPool(OLLAMA_HOST, OLLAMA_PORT)

# Server Availability Check
try:
    import fastapi
    import uvicorn
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

# Shared Patterns
COMPLEX_TRIGGERS = [
    "multiple modules", "integrate", "combine", "modular", "state machine", "safety", "failsafe", "logic", "protocol", "integration"
]
MODULE_PATTERNS = {
    "ble": ["ble", "bluetooth", "phone app", "remote"],
    "servo": ["servo", "flipper", "arm", "mg996", "sg90"],
    "motor": ["motor", "drive", "l298n", "movement", "wheels"],
    "safety": ["safety", "timeout", "failsafe", "emergency"],
    "battery": ["battery", "voltage", "power"],
    "sensor": ["sensor", "distance", "proximity", "ultrasonic", "ir"]
}