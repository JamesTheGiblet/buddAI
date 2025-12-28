#!/usr/bin/env python3
"""
BuddAI Executive v2.0 - Modular Builder
Breaks complex tasks into manageable chunks

Author: James Gilbert
License: MIT
"""

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



# --- Shadow Suggestion Engine ---
class ShadowSuggestionEngine:
    """Proactively suggests modules/settings based on user/project history."""
    def __init__(self, db_path):
        self.db_path = db_path

    def lookup_recent_module_usage(self, module, limit=5):
        """Look up recent usage patterns for a module from repo_index."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT file_path, content, last_modified FROM repo_index
            WHERE function_name LIKE ? OR file_path LIKE ?
            ORDER BY last_modified DESC LIMIT ?
            """,
            (f"%{module}%", f"%{module}%", limit)
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def suggest_for_module(self, module):
        """Return a proactive suggestion string for a module if pattern detected."""
        history = self.lookup_recent_module_usage(module)
        if not history:
            return None
        # Example: For 'motor', look for L298N and PWM frequency
        l298n_count = 0
        pwm_freqs = []
        for _, content, _ in history:
            if "L298N" in content or "l298n" in content:
                l298n_count += 1
            pwm_matches = re.findall(r'PWM_FREQ\s*=\s*(\d+)', content)
            pwm_freqs.extend([int(f) for f in pwm_matches])
            # Also look for explicit frequency in analogWrite or ledcSetup
            freq_matches = re.findall(r'(?:ledcSetup|analogWrite)\s*\([^,]+,\s*[^,]+,\s*(\d+)\)', content)
            pwm_freqs.extend([int(f) for f in freq_matches if f.isdigit()])
        if l298n_count >= 2:
            freq = max(set(pwm_freqs), key=pwm_freqs.count) if pwm_freqs else 500
            return f"I see you usually use the L298N with a {freq}Hz PWM frequency on the ESP32-C3. Should I prep that module?"
        return None

    def get_proactive_suggestion(self, user_input):
        """
        V3.0 Proactive Hook:
        1. Identify "Concept" (e.g., 'flipper')
        2. Query repo_index for James's most frequent companion modules
        3. If 'flipper' often appears with 'safety_timeout', suggest it.
        """
        # 1. Identify Concepts
        input_lower = user_input.lower()
        detected_modules = []
        for module, keywords in MODULE_PATTERNS.items():
            if any(kw in input_lower for kw in keywords):
                detected_modules.append(module)
        
        if not detected_modules:
            return None

        # 2. Query repo_index for correlations
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        suggestions = []
        for module in detected_modules:
            # Find files containing this module (simple heuristic)
            cursor.execute("SELECT content FROM repo_index WHERE content LIKE ? LIMIT 10", (f"%{module}%",))
            rows = cursor.fetchall()
            if not rows: continue
            
            # Check for companion modules
            companions = {}
            for (content,) in rows:
                content_lower = content.lower()
                for other_mod, other_kws in MODULE_PATTERNS.items():
                    if other_mod != module and other_mod not in detected_modules:
                        if any(kw in content_lower for kw in other_kws):
                            companions[other_mod] = companions.get(other_mod, 0) + 1
            
            # 3. Suggest if frequent (>50% correlation in sample)
            for other_mod, count in companions.items():
                if count >= len(rows) * 0.5:
                    suggestions.append(f"I noticed '{module}' often appears with '{other_mod}' in your repos. Want to include that?")
        
        conn.close()
        return " ".join(list(set(suggestions))) if suggestions else None

    def get_all_suggestions(self, user_input, generated_code):
        """Aggregate all proactive suggestions into a list."""
        suggestions = []
        
        # 1. Companion Modules
        companion = self.get_proactive_suggestion(user_input)
        if companion:
            suggestions.append(companion)
            
        # 2. Module Settings
        input_lower = user_input.lower()
        for module, keywords in MODULE_PATTERNS.items():
            if any(kw in input_lower for kw in keywords):
                s = self.suggest_for_module(module)
                if s:
                    suggestions.append(s)
        
        # 3. Forge Theory Check
        if ("motor" in input_lower or "servo" in input_lower) and "applyForge" not in generated_code:
            suggestions.append("Apply Forge Theory smoothing to movement?")
            
        # 4. Safety Check (L298N)
        if "L298N" in generated_code and "safety" not in generated_code.lower():
            suggestions.append("Drive system lacks safety timeout (GilBot_V2 uses 5s failsafe). Add that?")
            
        return suggestions


class BuddAI:
    """Executive with task breakdown"""

    def is_search_query(self, message):
        """Check if this is a search query that should query repo_index"""
        message_lower = message.lower()
        search_triggers = [
            "show me", "find", "search for", "list all",
            "what functions", "which repos", "do i have",
            "where did i", "have i used", "examples of",
            "show all", "display"
        ]
        return any(trigger in message_lower for trigger in search_triggers)

    def search_repositories(self, query):
        """Search repo_index for relevant functions and code"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM repo_index")
        count = cursor.fetchone()[0]
        print(f"\n🔍 Searching {count} indexed functions...\n")

        # Extract keywords from query
        keywords = re.findall(r'\b\w{4,}\b', query.lower())
        # Add specific search terms
        specific_terms = []
        if "exponential" in query.lower() or "decay" in query.lower():
            specific_terms.append("applyForge")
            specific_terms.append("exp(")
        if "forge" in query.lower():
            specific_terms.append("Forge")
        keywords.extend(specific_terms)
        # Search in function names and content
        search_conditions = []
        for keyword in keywords:
            search_conditions.append(f"function_name LIKE '%{keyword}%'")
            search_conditions.append(f"content LIKE '%{keyword}%'")
        if not search_conditions:
            print("❌ No search terms found")
            conn.close()
            return "No search terms provided."
        search_query = " OR ".join(search_conditions)
        sql = f"SELECT repo_name, file_path, function_name, content FROM repo_index WHERE {search_query} LIMIT 10"
        cursor.execute(sql)
        results = cursor.fetchall()
        conn.close()
        if not results:
            return f"❌ No functions found matching: {', '.join(keywords)}\n\nTry: /index <path> to index more repositories"
        # Format results
        output = f"✅ Found {len(results)} matches for: {', '.join(set(keywords))}\n\n"
        for i, (repo, file_path, func, content) in enumerate(results, 1):
            # Extract relevant snippet
            lines = content.split('\n')
            snippet_lines = []
            for line in lines[:30]:  # First 30 lines
                if any(kw in line.lower() for kw in keywords):
                    snippet_lines.append(line)
                if len(snippet_lines) >= 10:
                    break
            if not snippet_lines:
                snippet_lines = lines[:10]
            snippet = '\n'.join(snippet_lines)
            output += f"**{i}. {func}()** in {repo}\n"
            output += f"   📁 {Path(file_path).name}\n"
            output += f"   ```cpp\n{snippet}\n   ```\n"
            output += f"   ---\n\n"
        return output
    
    def __init__(self):
        self.ensure_data_dir()
        self.init_database()
        self.session_id = self.create_session()
        self.context_messages = []
        self.shadow_engine = ShadowSuggestionEngine(DB_PATH)
        
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
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS style_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                preference TEXT,
                confidence FLOAT,
                extracted_at TIMESTAMP
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

    def scan_style_signature(self):
        """V3.0: Analyze repo_index to extract style preferences."""
        print("\n🕵️  Scanning repositories for style signature...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get a sample of code
        cursor.execute("SELECT content FROM repo_index ORDER BY RANDOM() LIMIT 5")
        rows = cursor.fetchall()
        
        if not rows:
            print("❌ No code indexed. Run /index first.")
            conn.close()
            return
            
        code_sample = "\n---\n".join([r[0][:1000] for r in rows])
        
        prompt = f"""Analyze this code sample from James's repositories.
        Extract 3 distinct coding preferences or patterns.
        Format: Category: Preference
        
        Examples:
        - Serial: Uses 115200 baud
        - Safety: Uses non-blocking millis()
        - Pins: Prefers #define over const int
        
        Code Sample:
        {code_sample}
        """
        
        print("⚡ Analyzing with BALANCED model...")
        summary = self.call_model("balanced", prompt)
        
        # Store in DB
        timestamp = datetime.now().isoformat()
        lines = summary.split('\n')
        for line in lines:
            if ':' in line:
                parts = line.split(':', 1)
                category = parts[0].strip('- *')
                pref = parts[1].strip()
                cursor.execute(
                    "INSERT INTO style_preferences (category, preference, confidence, extracted_at) VALUES (?, ?, ?, ?)",
                    (category, pref, 0.8, timestamp)
                )
        
        conn.commit()
        conn.close()
        print(f"\n✅ Style Signature Updated:\n{summary}\n")

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
                
    def execute_modular_build(self, _, modules, plan):
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
        
    def apply_style_signature(self, generated_code):
        """Refine generated code to match James's specific naming and safety patterns"""
        # 1. Check for James's common function names (e.g., setupMotors vs init_motors)
        # 2. Ensure Forge Theory helpers are present if motion is detected
        # 3. Append a 'Proactive Note' if a common companion module is missing
        
        return generated_code

    def chat(self, user_message, force_model=None):
        """Main chat with smart routing and shadow suggestions"""
        style_context = self.retrieve_style_context(user_message)
        if style_context:
            self.context_messages.append({"role": "system", "content": style_context})


        self.save_message("user", user_message)
        self.context_messages.append({"role": "user", "content": user_message})


        if force_model:
            model = force_model
            print(f"\n⚡ Using {model.upper()} model (forced)...")
            response = self.call_model(model, user_message)
        elif self.is_complex(user_message):
            modules = self.extract_modules(user_message)
            plan = self.build_modular_plan(modules)
            print("\n" + "=" * 50)
            print("🎯 COMPLEX REQUEST DETECTED!")
            print(f"Modules needed: {', '.join(modules)}")
            print(f"Breaking into {len(plan)} manageable steps")
            print("=" * 50)
            response = self.execute_modular_build(user_message, modules, plan)
        elif self.is_search_query(user_message):
            # This is a search query - query the database
            response = self.search_repositories(user_message)
        elif self.is_simple_question(user_message):
            print("\n⚡ Using FAST model (simple question)...")
            response = self.call_model("fast", user_message)
        else:
            print("\n⚖️  Using BALANCED model...")
            response = self.call_model("balanced", user_message)

        # Apply Style Guard
        response = self.apply_style_signature(response)
        
        # Generate Suggestion Bar
        suggestions = self.shadow_engine.get_all_suggestions(user_message, response)
        if suggestions:
            bar = "\n\nPROACTIVE: > " + " ".join([f"{i+1}. {s}" for i, s in enumerate(suggestions)])
            response += bar

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
                        print("/scan - Scan style signature (V3.0)")
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
                    elif cmd == '/scan':
                        self.scan_style_signature()
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