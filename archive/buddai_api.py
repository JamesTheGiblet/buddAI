#!/usr/bin/env python3
"""
BuddAI Executive v2.0 - Modular Builder
Breaks complex tasks into manageable chunks

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
import re

# Configuration
OLLAMA_HOST = "localhost"
OLLAMA_PORT = 11434
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "conversations.db"

# Models
MODELS = {
    "fast": "qwen2.5-coder:1.5b",
    "balanced": "qwen2.5-coder:3b"
}

# Complexity triggers - if matched, break down the task
COMPLEX_TRIGGERS = [
    "complete", "entire", "full", "build entire", "build complete",
    "with ble and", "with servo and", "including", "all of"
]

# Module patterns we can detect
MODULE_PATTERNS = {
    "ble": ["bluetooth", "ble", "wireless"],
    "servo": ["servo", "flipper", "weapon"],
    "motor": ["motor", "drive", "movement", "l298n"],
    "safety": ["safety", "timeout", "failsafe", "emergency"],
    "battery": ["battery", "voltage", "power monitor"],
    "sensor": ["sensor", "distance", "proximity"]
}


class BuddAI:
    """Executive with task breakdown"""
    
    def __init__(self):
        self.ensure_data_dir()
        self.init_database()
        self.session_id = self.create_session()
        self.context_messages = []
        
        print("🧠 BuddAI Executive v2.0 - Modular Builder")
        print("=" * 50)
        print(f"Session: {self.session_id}")
        print(f"FAST (5-10s) | BALANCED (15-30s)")
        print(f"Smart task breakdown for complex requests")
        print("=" * 50)
        print("\nCommands: /fast, /balanced, /help, exit\n")
        
    def ensure_data_dir(self):
        DATA_DIR.mkdir(exist_ok=True)
        
    def init_database(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TIMESTAMP,
                ended_at TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP
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
            "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
            (datetime.now().isoformat(), self.session_id)
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
        
    def is_complex(self, message):
        """Check if request is too complex and should be broken down"""
        message_lower = message.lower()
        
        # Count complexity triggers
        trigger_count = sum(1 for trigger in COMPLEX_TRIGGERS if trigger in message_lower)
        
        # Count how many modules mentioned
        module_count = 0
        for module, keywords in MODULE_PATTERNS.items():
            if any(kw in message_lower for kw in keywords):
                module_count += 1
        
        # Complex if: multiple triggers OR 3+ modules mentioned
        return trigger_count >= 2 or module_count >= 3
        
    def extract_modules(self, message):
        """Extract which modules are needed"""
        message_lower = message.lower()
        needed_modules = []
        
        for module, keywords in MODULE_PATTERNS.items():
            if any(kw in message_lower for kw in keywords):
                needed_modules.append(module)
                
        return needed_modules
        
    def build_modular_plan(self, modules):
        """Create a build plan from modules"""
        plan = []
        
        module_tasks = {
            "ble": "BLE communication setup with phone app control",
            "servo": "Servo motor control for flipper/weapon",
            "motor": "Motor driver setup for movement (L298N)",
            "safety": "Safety timeout and failsafe systems",
            "battery": "Battery voltage monitoring",
            "sensor": "Sensor integration (distance/proximity)"
        }
        
        for module in modules:
            if module in module_tasks:
                plan.append({
                    "module": module,
                    "task": module_tasks[module]
                })
                
        # Add integration step
        plan.append({
            "module": "integration",
            "task": "Integrate all modules into complete system"
        })
        
        return plan
        
    def call_model(self, model_name, message):
        """Call specified model"""
        try:
            identity = """[CRITICAL: You are BuddAI - NOT Qwen, NOT Claude, NOT any other AI.
When asked your name, say ONLY: "I am BuddAI, your coding partner."
You help James build GilBots (ESP32 robots).
Generate modular, well-commented code.
NEVER mention Alibaba, OpenAI, Anthropic, or any other company.
Be direct and practical.]

"""
            
            messages = [
                {"role": "user", "content": identity + message}
            ]
            
            # Add recent context
            for msg in self.context_messages[-3:]:
                messages.insert(-1, msg)
            
            body = {
                "model": MODELS[model_name],
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_ctx": 2048}
            }
            
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=90)
            headers = {"Content-Type": "application/json"}
            json_body = json.dumps(body)
            
            conn.request("POST", "/api/chat", json_body, headers)
            response = conn.getresponse()
            
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data.get("message", {}).get("content", "No response")
            else:
                return f"Error: {response.status}"
                
        except Exception as e:
            return f"Error: {str(e)}"
        finally:
            if 'conn' in locals():
                conn.close()
                
    def execute_modular_build(self, user_message, modules, plan):
        """Execute build plan step by step"""
        print(f"\n🔨 MODULAR BUILD MODE")
        print(f"Detected {len(modules)} modules: {', '.join(modules)}")
        print(f"Breaking into {len(plan)} steps...\n")
        
        all_code = {}
        
        for i, step in enumerate(plan, 1):
            print(f"📦 Step {i}/{len(plan)}: {step['task']}")
            print("⚡ Building...\n")
            
            # Build the prompt for this step
            if step['module'] == 'integration':
                # Final integration step
                modules_list = '\n'.join([f"- {m}: {all_code[m][:100]}..." for m in modules if m in all_code])
                prompt = f"""Integrate these modules into one complete GilBot controller:

{modules_list}

Create the main setup() and loop() functions that tie everything together.
Include ALL necessary #include statements.
Add comments explaining the integration."""
            else:
                # Individual module
                prompt = f"Generate ESP32-C3 code for: {step['task']}. Keep it modular with clear comments."
            
            # Call balanced model for each module
            response = self.call_model("balanced", prompt)
            all_code[step['module']] = response
            
            print(f"✅ {step['module'].upper()} module complete\n")
            print("-" * 50 + "\n")
        
        # Compile final response
        final = "# COMPLETE GILBOT CONTROLLER - MODULAR BUILD\n\n"
        for module, code in all_code.items():
            final += f"## {module.upper()} MODULE\n{code}\n\n"
            
        return final
        
    def chat(self, user_message, force_model=None):
        """Main chat with modular breakdown"""
        # Save user message
        self.save_message("user", user_message)
        self.context_messages.append({"role": "user", "content": user_message})
        
        # Check if complex
        if self.is_complex(user_message) and not force_model:
            modules = self.extract_modules(user_message)
            plan = self.build_modular_plan(modules)
            
            print("\n" + "=" * 50)
            print("🎯 COMPLEX REQUEST DETECTED!")
            print(f"Modules needed: {', '.join(modules)}")
            print(f"Breaking into {len(plan)} manageable steps")
            print("=" * 50)
            
            response = self.execute_modular_build(user_message, modules, plan)
        else:
            # Simple request - use balanced model
            model = force_model or "balanced"
            print(f"\n⚡ Using {model.upper()} model...")
            response = self.call_model(model, user_message)
        
        # Save response
        self.save_message("assistant", response)
        self.context_messages.append({"role": "assistant", "content": response})
        
        return response
        
    def run(self):
        """Main loop"""
        try:
            force_model = None
            
            while True:
                user_input = input("\nJames: ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ['exit', 'quit']:
                    print("\n👋 Later!")
                    self.end_session()
                    break
                    
                if user_input.startswith('/'):
                    cmd = user_input.lower()
                    if cmd == '/fast':
                        force_model = "fast"
                        print("⚡ Next: FAST model")
                        continue
                    elif cmd == '/balanced':
                        force_model = "balanced"
                        print("⚖️  Next: BALANCED model")
                        continue
                    elif cmd == '/help':
                        print("\n💡 Commands:")
                        print("/fast - Use fast model")
                        print("/balanced - Use balanced model")
                        print("/help - This message")
                        print("exit - End session\n")
                        continue
                    else:
                        print("\nUnknown command. Type /help")
                        continue
                
                # Chat
                response = self.chat(user_input, force_model)
                print(f"\nBuddAI:\n{response}\n")
                
                force_model = None
                    
        except KeyboardInterrupt:
            print("\n\n👋 Bye!")
            self.end_session()


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
        print("❌ Ollama not running. Start: ollama serve")
        sys.exit(1)
        
    buddai = BuddAI()
    buddai.run()


if __name__ == "__main__":
    main()