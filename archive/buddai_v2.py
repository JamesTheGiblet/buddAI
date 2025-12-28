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
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repo_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                repo_name TEXT,
                function_name TEXT,
                content TEXT,
                last_modified TIMESTAMP
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
        
    def index_local_repositories(self, root_path):
        """Crawl directories and index .py, .ino, and .cpp files"""
        import ast
        
        print(f"\n🔍 Indexing repositories in: {root_path}")
        path = Path(root_path)
        
        if not path.exists():
            print(f"❌ Path not found: {root_path}")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        count = 0
        
        for file_path in path.rglob('*'):
            if file_path.is_file() and file_path.suffix in ['.py', '.ino', '.cpp', '.h']:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    functions = []
                    
                    # Python parsing
                    if file_path.suffix == '.py':
                        try:
                            tree = ast.parse(content)
                            for node in ast.walk(tree):
                                if isinstance(node, ast.FunctionDef):
                                    functions.append(node.name)
                        except:
                            pass
                            
                    # C++/Arduino parsing
                    elif file_path.suffix in ['.ino', '.cpp', '.h']:
                        matches = re.findall(r'\b(?:void|int|bool|float|double|String|char)\s+(\w+)\s*\(', content)
                        functions.extend(matches)
                    
                    # Determine repo name
                    try:
                        repo_name = file_path.relative_to(path).parts[0]
                    except:
                        repo_name = "unknown"
                        
                    timestamp = datetime.fromtimestamp(file_path.stat().st_mtime)
                    
                    for func in functions:
                        cursor.execute("""
                            INSERT INTO repo_index (file_path, repo_name, function_name, content, last_modified)
                            VALUES (?, ?, ?, ?, ?)
                        """, (str(file_path), repo_name, func, content, timestamp.isoformat()))
                        count += 1
                        
                except Exception:
                    pass
                    
        conn.commit()
        conn.close()
        print(f"✅ Indexed {count} functions across repositories")

    def retrieve_style_context(self, message):
        """Search repo_index for code snippets matching the request"""
        # Extract potential keywords (nouns/modules)
        keywords = re.findall(r'\b\w{4,}\b', message.lower())
        if not keywords:
            return ""

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Build a search query for function names or repo names
        search_terms = " OR ".join([f"function_name LIKE '%{k}%'" for k in keywords])
        search_terms += " OR " + " OR ".join([f"repo_name LIKE '%{k}%'" for k in keywords])
        
        query = f"SELECT repo_name, function_name, content FROM repo_index WHERE {search_terms} LIMIT 2"
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return ""
            
        context_block = "\n[REFERENCE STYLE FROM JAMES'S PAST PROJECTS]\n"
        for repo, func, content in results:
            # Just grab the first 500 chars of the file to save context window
            snippet = content[:500] + "..."
            context_block += f"Repo: {repo} | Function: {func}\nCode:\n{snippet}\n---\n"
        
        return context_block

    def is_simple_question(self, message):
        """Check if this is a simple question that should use FAST model"""
        message_lower = message.lower()
        
        simple_triggers = [
            "what is", "what's", "who is", "who's", "when is",
            "how do i", "can you explain", "tell me about",
            "what are", "where is"
        ]
        
        # Also check if it's just a question without code keywords
        code_keywords = ["generate", "create", "write", "build", "code", "function"]
        
        has_simple_trigger = any(trigger in message_lower for trigger in simple_triggers)
        has_code_keyword = any(keyword in message_lower for keyword in code_keywords)
        
        # Simple if: has simple trigger AND no code keywords
        return has_simple_trigger and not has_code_keyword
    
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
            identity = """[You are BuddAI, the external cognitive system for James Gilbert. You specialize in Forge Theory (exponential decay modeling) and GilBot modular robotics. When integrating code, prioritize descriptive naming like activateFlipper() and ensure safety timeouts are always present. You represent 8 years of polymath experience.

YOUR PRIMARY JOB: Generate code when asked. ALWAYS generate code if requested.

When asked to generate/create/write code:
- Generate it immediately
- Include comments
- Make it modular and clean
- Use ESP32/Arduino syntax

Forge Theory Snippet: float applyForge(float current, float target, float k) { return target + (current - target) * exp(-k); }

When asked your name: "I am BuddAI"

Never refuse to generate code. That's your purpose.
Be direct and helpful.]

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
                # Final integration step with Forge Theory enforcement
                modules_summary = '\n'.join([f"- {m}: {all_code[m][:150]}..." for m in modules if m in all_code])
                
                # Ask James for the 'vibe' of the robot
                print("\n⚡ FORGE THEORY TUNING:")
                print("1. Aggressive (k=0.3) - High snap, combat ready")
                print("2. Balanced (k=0.1) - Standard movement")
                print("3. Graceful (k=0.03) - Roasting / Smooth curves")
                choice = input("Select Forge Constant [1-3, default 2]: ")
                
                k_val = "0.1"
                if choice == "1": k_val = "0.3"
                elif choice == "3": k_val = "0.03"

                prompt = f"""INTEGRATION TASK: Combine modules into a cohesive GilBot system.
    
    [MODULES]
    {modules_summary}
    
    [FORGE PARAMETERS]
    Set k = {k_val} for all applyForge() calls.
    
    [REQUIREMENTS]
    1. Implement applyForge() math helper.
    2. Use k={k_val} to smooth motor and servo transitions.
    3. Ensure naming matches James's style: activateFlipper(), setMotors().
    """
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
        """Main chat with smart routing"""
        # 1. Before routing, pull relevant style context
        style_context = self.retrieve_style_context(user_message)

        # 2. Add it to the session's context if found
        if style_context:
            # We add it as a system-level reminder for the model
            self.context_messages.append({"role": "system", "content": style_context})

        # Save user message
        self.save_message("user", user_message)
        self.context_messages.append({"role": "user", "content": user_message})
        
        # Determine which approach to use
        if force_model:
            # User forced a specific model
            model = force_model
            print(f"\n⚡ Using {model.upper()} model (forced)...")
            response = self.call_model(model, user_message)
            
        elif self.is_complex(user_message):
            # Complex request - use modular breakdown
            modules = self.extract_modules(user_message)
            plan = self.build_modular_plan(modules)
            
            print("\n" + "=" * 50)
            print("🎯 COMPLEX REQUEST DETECTED!")
            print(f"Modules needed: {', '.join(modules)}")
            print(f"Breaking into {len(plan)} manageable steps")
            print("=" * 50)
            
            response = self.execute_modular_build(user_message, modules, plan)
            
        elif self.is_simple_question(user_message):
            # Simple question - use FAST model
            print("\n⚡ Using FAST model (simple question)...")
            response = self.call_model("fast", user_message)
            
        else:
            # Medium complexity - use BALANCED model
            print("\n⚖️  Using BALANCED model...")
            response = self.call_model("balanced", user_message)
        
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
                        print("/index <path> - Index local repositories")
                        print("/help - This message")
                        print("exit - End session\n")
                        continue
                    elif cmd.startswith('/index'):
                        parts = user_input.split(maxsplit=1)
                        if len(parts) > 1:
                            self.index_local_repositories(parts[1])
                        else:
                            print("Usage: /index <path_to_repos>")
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