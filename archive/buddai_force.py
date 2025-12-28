#!/usr/bin/env python3
"""
BuddAI - Brute Force Edition
Injects identity directly into every prompt since system prompts aren't working

Author: James Gilbert
License: MIT
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import http.client

# Configuration
OLLAMA_HOST = "localhost"
OLLAMA_PORT = 11434
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "conversations.db"
OLLAMA_MODEL = "qwen2.5-coder:1.5b"  # Fast model for slow laptop

# Identity that gets PREPENDED to EVERY message
IDENTITY = """[You are BuddAI (not Qwen, not any other AI). You help James build GilBots.
When asked for code, GENERATE THE CODE. Be direct and practical.]

James: """


class BuddAI:
    """BuddAI with forced identity injection"""
    
    def __init__(self):
        self.ensure_data_dir()
        self.init_database()
        self.session_id = self.create_session()
        
        # Load context from ALL past sessions (last 10 messages)
        self.context_messages = self.load_all_history(10)
        
        print("⚡ BuddAI - Brute Force Mode")
        print("=" * 50)
        print(f"Session: {self.session_id}")
        print(f"Model: {OLLAMA_MODEL}")
        print(f"Loaded: {len(self.context_messages)} past messages")
        print("=" * 50)
        print("\nCommands: /help, /clear, exit\n")
        
    def ensure_data_dir(self):
        DATA_DIR.mkdir(exist_ok=True)
        
    def init_database(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                message_count INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        conn.commit()
        conn.close()
        
    def create_session(self):
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (session_id, started_at) VALUES (?, ?)",
            (session_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return session_id
        
    def end_session(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET ended_at = ?, message_count = ? WHERE session_id = ?",
            (datetime.now().isoformat(), len(self.context_messages), self.session_id)
        )
        conn.commit()
        conn.close()
        
    def save_message(self, role, content):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (self.session_id, role, content, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    
    def load_all_history(self, limit=10):
        """Load recent messages from ALL sessions for persistent memory"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content FROM messages 
            ORDER BY timestamp DESC 
            LIMIT ?
            """,
            (limit,)
        )
        messages = cursor.fetchall()
        conn.close()
        
        # Reverse to get chronological order
        return [{"role": role, "content": content} for role, content in reversed(messages)]
        
    def call_ollama_api(self, user_message):
        """Call Ollama with context summary"""
        try:
            # Build context summary from recent messages
            context_summary = ""
            if len(self.context_messages) > 0:
                recent = self.context_messages[-5:]
                context_summary = "\nRecent conversation:\n"
                for msg in recent:
                    role = "James" if msg["role"] == "user" else "BuddAI"
                    preview = msg["content"][:100]
                    context_summary += f"{role}: {preview}\n"
                context_summary += "\n"
            
            # Add ALL historical messages
            messages = []
            for msg in self.context_messages[-5:]:
                messages.append(msg)
            
            # Add current message with identity AND context summary
            forced_prompt = IDENTITY + context_summary + user_message
            messages.append({"role": "user", "content": forced_prompt})
            
            body = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_ctx": 2048
                }
            }
            
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=60)
            headers = {"Content-Type": "application/json"}
            json_body = json.dumps(body)
            
            conn.request("POST", "/api/chat", json_body, headers)
            response = conn.getresponse()
            
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data.get("message", {}).get("content", "No response")
            else:
                error_text = response.read().decode('utf-8')
                return f"API Error: {error_text[:100]}"
                
        except Exception as e:
            return f"Error: {str(e)}"
        finally:
            if 'conn' in locals():
                conn.close()
                
    def chat(self, user_message):
        """Main chat"""
        # Save the CLEAN user message (without identity prefix)
        self.save_message("user", user_message)
        user_msg = {"role": "user", "content": user_message}
        self.context_messages.append(user_msg)
        
        print("\n⚡ Thinking...\n")
        response = self.call_ollama_api(user_message)
        
        self.save_message("assistant", response)
        assistant_msg = {"role": "assistant", "content": response}
        self.context_messages.append(assistant_msg)
        
        return response
        
    def show_help(self):
        print("\n💡 Commands")
        print("=" * 50)
        print("/help   - This message")
        print("/clear  - Clear context")
        print("/stats  - Session stats")
        print("exit    - End session")
        print("=" * 50 + "\n")
        
    def clear_context(self):
        self.context_messages = []
        print("\n🧹 Cleared\n")
        
    def show_stats(self):
        print(f"\n📊 Messages this session: {len(self.context_messages) // 2}\n")
        
    def run(self):
        """Main loop"""
        try:
            while True:
                user_input = input("James: ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ['exit', 'quit']:
                    print("\n👋 Later!")
                    self.end_session()
                    break
                    
                if user_input.startswith('/'):
                    if user_input == '/help':
                        self.show_help()
                    elif user_input == '/clear':
                        self.clear_context()
                    elif user_input == '/stats':
                        self.show_stats()
                    else:
                        print("\nUnknown command. Type /help\n")
                    continue
                    
                response = self.chat(user_input)
                print(f"\nBuddAI: {response}\n")
                
        except KeyboardInterrupt:
            print("\n\n👋 Bye!")
            self.end_session()
        except Exception as e:
            print(f"\n❌ {e}")
            self.end_session()
            raise


def check_ollama():
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=5)
        conn.request("GET", "/api/tags")
        response = conn.getresponse()
        conn.close()
        return response.status == 200
    except:
        return False


def main():
    if not check_ollama():
        print("❌ Ollama not running. Start it: ollama serve")
        sys.exit(1)
        
    buddai = BuddAI()
    buddai.run()


if __name__ == "__main__":
    main()