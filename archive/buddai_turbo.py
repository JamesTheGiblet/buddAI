#!/usr/bin/env python3
"""
BuddAI Turbo - Optimized for Slow Hardware
Switchable performance modes + model selection

Author: James Gilbert (JamesTheGiblet)
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

# Available models (fastest to slowest)
MODELS = {
    "tiny": "qwen2.5-coder:1.5b",      # 5-10 sec, basic
    "fast": "deepseek-coder:1.3b",     # 10-20 sec, decent
    "balanced": "qwen2.5-coder:3b",    # 20-40 sec, good
    "quality": "deepseek-coder:6.7b"   # 40-90 sec, best
}

# System prompts (lean to verbose)
PROMPTS = {
    "turbo": """I am BuddAI. James's coding partner.

James: Polymath. 115+ repos. Builds GilBots (ESP32 combat robots). Forge Theory creator.

My job: Generate code. Remember context. Be direct. No corporate speak.

Current: GilBot #1 flipper, ESP32-C3, 15kg servo.""",
    
    "balanced": """I am BuddAI, James Gilbert's coding partner.

James builds:
- GilBots: ESP32-C3 combat robots (NOW)
- CoffeeForge, CannaForge, BlockForge
- 115+ GitHub repos, 8+ years experience

His style: Modular, commented, practical. Function names like activateFlipper() not flip().

I generate code matching his style. I remember our conversations. I'm direct and helpful.""",
    
    "detailed": """I am BuddAI, James Gilbert's IP AI Exocortex and coding partner.

WHO JAMES IS:
- Polymath creator: robotics, 3D printing, coffee/cannabis science
- JamesTheGiblet on GitHub: 115+ repositories
- Created Forge Theory: exponential decay framework
- Works in 20-hour creative cycles, rapid prototyping
- Expert debugger who uses AI for code generation

CURRENT PROJECT:
GilBot #1: Flipper combat robot, ESP32-C3, 15kg servo, BLE phone control

HIS CODING STYLE:
- Modular functions (small, focused)
- Descriptive names: activateFlipper() not flip()
- Inline comments explaining WHY
- Clean, simple, maintainable

MY ROLE:
- Generate code in his style
- Remember all conversations (I have persistent memory)
- Suggest approaches from his past work
- Be direct, practical, honest
- Learn from corrections

I am his partner. I work WITH him, not FOR him."""
}

# Default settings
DEFAULT_MODEL = "tiny"      # Fast responses on slow laptop
DEFAULT_PROMPT = "balanced" # Good balance of context and speed


class BuddAI:
    """Turbo BuddAI with performance modes"""
    
    def __init__(self):
        """Initialize"""
        self.ensure_data_dir()
        self.init_database()
        self.session_id = self.create_session()
        self.context_messages = []
        
        # Performance settings
        self.current_model = DEFAULT_MODEL
        self.current_prompt = DEFAULT_PROMPT
        self.max_context = 5  # Start conservative
        
        self.show_banner()
        
    def show_banner(self):
        """Show startup banner"""
        print("⚡ BuddAI TURBO - Optimized for Speed")
        print("=" * 50)
        print(f"Session: {self.session_id}")
        print(f"Mode: {self.current_model.upper()} + {self.current_prompt.upper()}")
        print(f"Model: {MODELS[self.current_model]}")
        print(f"Context: {self.max_context} messages")
        print("=" * 50)
        print("\nCommands: /help, /mode, /model, exit\n")
        
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
                message_count INTEGER DEFAULT 0,
                model_used TEXT,
                prompt_mode TEXT
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
            "INSERT INTO sessions (session_id, started_at, model_used, prompt_mode) VALUES (?, ?, ?, ?)",
            (session_id, datetime.now().isoformat(), DEFAULT_MODEL, DEFAULT_PROMPT)
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
        
    def call_ollama_api(self, user_message):
        """Call Ollama with current settings"""
        try:
            messages = [
                {"role": "system", "content": PROMPTS[self.current_prompt]}
            ]
            
            # Add limited context
            for msg in self.context_messages[-self.max_context:]:
                messages.append(msg)
            
            messages.append({"role": "user", "content": user_message})
            
            body = {
                "model": MODELS[self.current_model],
                "messages": messages,
                "stream": False,
                "options": {
                    "num_ctx": 2048,  # Smaller context window = faster
                    "temperature": 0.7
                }
            }
            
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=180)
            headers = {"Content-Type": "application/json"}
            json_body = json.dumps(body)
            
            conn.request("POST", "/api/chat", json_body, headers)
            response = conn.getresponse()
            
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data.get("message", {}).get("content", "No response")
            else:
                error_text = response.read().decode('utf-8')
                return f"API Error {response.status}: {error_text}"
                
        except Exception as e:
            return f"Error: {str(e)}"
        finally:
            if 'conn' in locals():
                conn.close()
                
    def chat(self, user_message):
        """Main chat"""
        self.save_message("user", user_message)
        user_msg = {"role": "user", "content": user_message}
        self.context_messages.append(user_msg)
        
        print(f"\n⚡ Thinking ({self.current_model})...\n")
        response = self.call_ollama_api(user_message)
        
        self.save_message("assistant", response)
        assistant_msg = {"role": "assistant", "content": response}
        self.context_messages.append(assistant_msg)
        
        return response
        
    def show_help(self):
        print("\n💡 Commands")
        print("=" * 50)
        print("/help      - This message")
        print("/mode      - Change prompt mode (turbo/balanced/detailed)")
        print("/model     - Change model (tiny/fast/balanced/quality)")
        print("/context N - Set context size (1-20)")
        print("/stats     - Session stats")
        print("/clear     - Clear context")
        print("exit       - End session")
        print("=" * 50)
        print(f"\nCurrent: {self.current_model} model + {self.current_prompt} prompt")
        print(f"Context: {self.max_context} messages\n")
        
    def change_mode(self):
        print("\nPrompt Modes:")
        print("1. turbo    - Ultra-concise (fastest)")
        print("2. balanced - Normal detail")
        print("3. detailed - Full context")
        choice = input("\nChoose mode (1-3): ").strip()
        
        modes = {"1": "turbo", "2": "balanced", "3": "detailed"}
        if choice in modes:
            self.current_prompt = modes[choice]
            print(f"✅ Switched to {self.current_prompt} mode\n")
        else:
            print("❌ Invalid choice\n")
            
    def change_model(self):
        print("\nModels:")
        print("1. tiny     - 1.5b (5-10s, basic)")
        print("2. fast     - 1.3b (10-20s, decent)")  
        print("3. balanced - 3b (20-40s, good)")
        print("4. quality  - 6.7b (40-90s, best)")
        choice = input("\nChoose model (1-4): ").strip()
        
        models = {"1": "tiny", "2": "fast", "3": "balanced", "4": "quality"}
        if choice in models:
            self.current_model = models[choice]
            print(f"✅ Switched to {self.current_model} ({MODELS[self.current_model]})\n")
        else:
            print("❌ Invalid choice\n")
            
    def set_context(self, n):
        try:
            n = int(n)
            if 1 <= n <= 20:
                self.max_context = n
                print(f"✅ Context set to {n} messages\n")
            else:
                print("❌ Context must be 1-20\n")
        except:
            print("❌ Invalid number\n")
            
    def show_stats(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (self.session_id,))
        session_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_count = cursor.fetchone()[0]
        
        conn.close()
        
        print("\n📊 Stats")
        print("=" * 50)
        print(f"This session: {session_count} messages")
        print(f"Total: {total_count} messages")
        print(f"Model: {MODELS[self.current_model]}")
        print(f"Prompt: {self.current_prompt}")
        print(f"Context: {self.max_context}")
        print("=" * 50 + "\n")
        
    def clear_context(self):
        self.context_messages = []
        print("\n🧹 Context cleared\n")
        
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
                    cmd = user_input.lower().split()
                    if cmd[0] == '/help':
                        self.show_help()
                    elif cmd[0] == '/mode':
                        self.change_mode()
                    elif cmd[0] == '/model':
                        self.change_model()
                    elif cmd[0] == '/context' and len(cmd) > 1:
                        self.set_context(cmd[1])
                    elif cmd[0] == '/stats':
                        self.show_stats()
                    elif cmd[0] == '/clear':
                        self.clear_context()
                    else:
                        print(f"\nUnknown command. Type /help\n")
                    continue
                    
                response = self.chat(user_input)
                print(f"\nBuddAI: {response}\n")
                
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted")
            self.end_session()
        except Exception as e:
            print(f"\n❌ Error: {e}")
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
    print("⚡ BuddAI Turbo Starting...")
    
    if not check_ollama():
        print("❌ Ollama not running")
        print("\nStart it: ollama serve")
        sys.exit(1)
        
    print("✅ Ollama ready\n")
    
    buddai = BuddAI()
    buddai.run()


if __name__ == "__main__":
    main()