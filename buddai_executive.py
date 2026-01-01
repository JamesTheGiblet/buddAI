#!/usr/bin/env python3
from urllib.parse import urlparse
import sys, os, json, logging, sqlite3, datetime, http.client, re, zipfile, shutil, queue, socket, argparse, io
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Union, Generator

from anthropic import BaseModel
import psutil

from buddai_logic import CodeValidator, HardwareProfile, LearningMetrics
from buddai_memory import AdaptiveLearner, ShadowSuggestionEngine, SmartLearner
from buddai_shared import DATA_DIR, DB_PATH, MODELS, OLLAMA_HOST, OLLAMA_PORT, COMPLEX_TRIGGERS, MODULE_PATTERNS, SERVER_AVAILABLE

class OllamaConnectionPool:
    def __init__(self, host: str, port: int, max_size: int = 10):
        self.host = host
        self.port = port
        self.pool: queue.Queue = queue.Queue(maxsize=max_size)
        
    def get_connection(self) -> http.client.HTTPConnection:
        try:
            return self.pool.get_nowait()
        except queue.Empty:
            return http.client.HTTPConnection(self.host, self.port, timeout=90)
            
    def return_connection(self, conn: http.client.HTTPConnection):
        try:
            self.pool.put_nowait(conn)
        except queue.Full:
            conn.close()

OLLAMA_POOL = OllamaConnectionPool(OLLAMA_HOST, OLLAMA_PORT)


# --- Shadow Suggestion Engine ---

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_TYPES = [
    "application/zip", "application/x-zip-compressed", "application/octet-stream",
    "text/x-python", "text/plain", "text/x-c++src", "text/x-csrc", "text/javascript", "text/html", "text/css"
]
MAX_UPLOAD_FILES = 20

class BuddAI:
    """Executive with task breakdown"""

    def is_search_query(self, message: str) -> bool:
        """Check if this is a search query that should query repo_index"""
        message_lower = message.lower()
        search_triggers = [
            "show me", "find", "search for", "list all",
            "what functions", "which repos", "do i have",
            "where did i", "have i used", "examples of",
            "show all", "display"
        ]
        return any(trigger in message_lower for trigger in search_triggers)

    def search_repositories(self, query: str) -> str:
        """Search repo_index for relevant functions and code"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM repo_index WHERE user_id = ?", (self.user_id,))
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
        
        if not keywords:
            print("❌ No search terms found")
            conn.close()
            return "No search terms provided."
            
        # Build parameterized query
        conditions = []
        params = []
        for keyword in keywords:
            conditions.append("(function_name LIKE ? OR content LIKE ? OR repo_name LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
            
        sql = f"SELECT repo_name, file_path, function_name, content FROM repo_index WHERE ({' OR '.join(conditions)}) AND user_id = ? ORDER BY last_modified DESC LIMIT 10"
        params.append(self.user_id)
        
        cursor.execute(sql, params)
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
            output += f"\n```cpp\n{snippet}\n```\n"
            output += f"   ---\n\n"
        return output
    
    def __init__(self, user_id: str = "default", server_mode: bool = False):
        self.user_id = user_id
        self.last_generated_id = None
        self.last_prompt_debug = None
        self.ensure_data_dir()
        self.init_database()
        self.session_id = self.create_session()
        self.server_mode = server_mode
        self.context_messages = []
        self.shadow_engine = ShadowSuggestionEngine(DB_PATH, self.user_id)
        self.learner = SmartLearner()
        self.hardware_profile = HardwareProfile()
        self.current_hardware = "ESP32-C3"
        self.validator = CodeValidator()
        self.adaptive_learner = AdaptiveLearner()
        self.metrics = LearningMetrics()
        self.fine_tuner = ModelFineTuner()
        
        print("BuddAI Executive v3.8 - Multi-User & Fine-Tuning Ready")
        print("=" * 50)
        print(f"Session: {self.session_id}")
        print(f"FAST (5-10s) | BALANCED (15-30s)")
        print(f"Smart task breakdown for complex requests")
        print("=" * 50)
        print("\nCommands: /fast, /balanced, /help, exit\n")
        
    def ensure_data_dir(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        
    def init_database(self) -> None:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                title TEXT
            )
        """)
        
        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN title TEXT")
        except sqlite3.OperationalError:
            pass
            
        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass

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
                user_id TEXT,
                file_path TEXT,
                repo_name TEXT,
                function_name TEXT,
                content TEXT,
                last_modified TIMESTAMP
            )
        """)

        try:
            cursor.execute("ALTER TABLE repo_index ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS style_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                category TEXT,
                preference TEXT,
                confidence FLOAT,
                extracted_at TIMESTAMP
            )
        """)
        
        try:
            cursor.execute("ALTER TABLE style_preferences ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                positive BOOLEAN,
                timestamp TIMESTAMP
            )
        """)

        try:
            cursor.execute("ALTER TABLE feedback ADD COLUMN comment TEXT")
        except sqlite3.OperationalError:
            pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                original_code TEXT,
                corrected_code TEXT,
                reason TEXT,
                context TEXT
            )
        """)

        try:
            cursor.execute("ALTER TABLE corrections ADD COLUMN processed BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compilation_log (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                code TEXT,
                success BOOLEAN,
                errors TEXT,
                hardware TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_rules (
                id INTEGER PRIMARY KEY,
                rule_text TEXT,
                pattern_find TEXT,
                pattern_replace TEXT,
                context TEXT,
                confidence FLOAT,
                learned_from TEXT,
                times_applied INTEGER DEFAULT 0
            )
        """)

        conn.commit()
        conn.close()
        
    def create_session(self) -> str:
        now = datetime.now()
        base_id = now.strftime("%Y%m%d_%H%M%S")
        session_id = base_id
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        counter = 0
        while True:
            try:
                cursor.execute(
                    "INSERT INTO sessions (session_id, user_id, started_at) VALUES (?, ?, ?)",
                    (session_id, self.user_id, now.isoformat())
                )
                conn.commit()
                break
            except sqlite3.IntegrityError:
                counter += 1
                session_id = f"{base_id}_{counter}"
                
        conn.close()
        return session_id
        
    def end_session(self) -> None:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
            (datetime.now().isoformat(), self.session_id)
        )
        conn.commit()
        conn.close()
        
    def save_message(self, role: str, content: str) -> int:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (self.session_id, role, content, datetime.now().isoformat())
        )
        msg_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return msg_id
        
    def index_local_repositories(self, root_path: str) -> None:
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
            if file_path.is_file() and file_path.suffix in ['.py', '.ino', '.cpp', '.h', '.js', '.jsx', '.html', '.css']:
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

                    # JS/Web parsing
                    elif file_path.suffix in ['.js', '.jsx']:
                        matches = re.findall(r'(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*?\)?\s*=>)', content)
                        functions.extend([m[0] or m[1] for m in matches if m[0] or m[1]])

                    # HTML/CSS - Index as whole file
                    elif file_path.suffix in ['.html', '.css']:
                        functions.append("file_content")
                    
                    # Determine repo name
                    try:
                        repo_name = file_path.relative_to(path).parts[0]
                    except:
                        repo_name = "unknown"
                        
                    timestamp = datetime.fromtimestamp(file_path.stat().st_mtime)
                    
                    for func in functions:
                        cursor.execute("""
                            INSERT INTO repo_index (user_id, file_path, repo_name, function_name, content, last_modified)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (self.user_id, str(file_path), repo_name, func, content, timestamp.isoformat()))
                        count += 1
                        
                except Exception:
                    pass
                    
        conn.commit()
        conn.close()
        print(f"✅ Indexed {count} functions across repositories")

    def retrieve_style_context(self, message: str) -> str:
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
        
        query = f"SELECT repo_name, function_name, content FROM repo_index WHERE ({search_terms}) AND user_id = ? LIMIT 2"
        
        cursor.execute(query, (self.user_id,))
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

    def scan_style_signature(self) -> None:
        """V3.0: Analyze repo_index to extract style preferences."""
        print("\n🕵️  Scanning repositories for style signature...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get a sample of code
        cursor.execute("SELECT content FROM repo_index WHERE user_id = ? ORDER BY RANDOM() LIMIT 5", (self.user_id,))
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
        summary = self.call_model("balanced", prompt, system_task=True)
        
        # Store in DB
        timestamp = datetime.now().isoformat()
        lines = summary.split('\n')
        for line in lines:
            if ':' in line:
                parts = line.split(':', 1)
                category = parts[0].strip('- *')
                pref = parts[1].strip()
                cursor.execute(
                    "INSERT INTO style_preferences (user_id, category, preference, confidence, extracted_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (self.user_id, category, pref, 0.8, timestamp)
                )
        
        conn.commit()
        conn.close()
        print(f"\n✅ Style Signature Updated:\n{summary}\n")

    def get_recent_context(self, limit: int = 5) -> str:
        """Get recent chat context as a string"""
        return json.dumps(self.context_messages[-limit:])

    def save_correction(self, original_code: str, corrected_code: str, reason: str):
        """Store when James fixes BuddAI's code"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                original_code TEXT,
                corrected_code TEXT,
                reason TEXT,
                context TEXT
            )
        """)
        
        cursor.execute("""
            INSERT INTO corrections 
            (timestamp, original_code, corrected_code, reason, context)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            original_code,
            corrected_code,
            reason,
            self.get_recent_context()
        ))
        
        conn.commit()
        conn.close()

    def detect_hardware(self, message: str) -> str:
        """Wrapper to detect hardware from message or return current default"""
        hw = self.hardware_profile.detect_hardware(message)
        return hw if hw else self.current_hardware

    def get_applicable_rules(self, user_message: str) -> List[Dict]:
        """Get rules relevant to the user message"""
        # user_message is currently unused
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Fetch rules with reasonable confidence
        cursor.execute("SELECT rule_text, confidence FROM code_rules WHERE confidence > 0.6 ORDER BY confidence DESC")
        rows = cursor.fetchall()
        conn.close()
        return [{"rule_text": r[0], "confidence": r[1]} for r in rows]

    def get_style_summary(self) -> str:
        """Get summary of learned style preferences"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT category, preference FROM style_preferences WHERE confidence > 0.6")
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "Standard coding style."
        return ", ".join([f"{r[0]}: {r[1]}" for r in rows])

    def classify_hardware(self, user_message: str) -> dict:
        """Detect what hardware this question is about"""
        
        hardware = {
            "servo": False,
            "dc_motor": False,
            "button": False,
            "led": False,
            "sensor": False,
            "weapon": False
        }
        
        msg_lower = user_message.lower()
        
        # Helper to check keywords
        def has_keywords(text, keywords):
            return any(word in text for word in keywords)

        # Keyword definitions
        servo_kws = ['servo', 'mg996', 'sg90']
        motor_kws = ['l298n', 'dc motor', 'motor driver', 'motor control']
        button_kws = ['button', 'switch', 'trigger']
        led_kws = ['led', 'light', 'brightness']
        led_kws = ['led', 'light', 'brightness', 'indicator']
        # Removed 'state machine' from weapon_kws to allow abstract logic
        weapon_kws = ['weapon', 'combat', 'arming', 'fire', 'spinner', 'flipper'] 
        logic_kws = ['state machine', 'logic', 'structure', 'flow', 'armed', 'disarmed']

        # 1. Check current message first
        detected_in_current = False
        
        if has_keywords(msg_lower, servo_kws): 
            hardware["servo"] = True
            detected_in_current = True
        if has_keywords(msg_lower, motor_kws): 
            hardware["dc_motor"] = True
            detected_in_current = True
        if has_keywords(msg_lower, button_kws): 
            hardware["button"] = True
            detected_in_current = True
        if has_keywords(msg_lower, led_kws): 
            hardware["led"] = True
            detected_in_current = True
        if has_keywords(msg_lower, weapon_kws): 
            hardware["weapon"] = True
            detected_in_current = True
        if has_keywords(msg_lower, logic_kws):
            # Logic detected: Clear context (don't set any hardware)
            detected_in_current = True
            
        # 2. Context Switching: Only look back if NO hardware/logic detected in current message
        # and message is short (likely a follow-up command like "make it spin")
        if not detected_in_current and len(user_message.split()) < 10 and self.context_messages:
            recent = " ".join([m['content'].lower() for m in self.context_messages[-2:] if m['role'] == 'user'])
            
            if has_keywords(recent, servo_kws): hardware["servo"] = True
            if has_keywords(recent, motor_kws): hardware["dc_motor"] = True
            if has_keywords(recent, button_kws): hardware["button"] = True
            if has_keywords(recent, led_kws): hardware["led"] = True
            if has_keywords(recent, weapon_kws): hardware["weapon"] = True
            
        return hardware

    def get_all_rules(self) -> List[str]:
        """Get all learned rules as text"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT rule_text FROM code_rules ORDER BY confidence DESC LIMIT 50")
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def filter_rules_by_hardware(self, all_rules, hardware):
        """Only return rules relevant to detected hardware"""
        
        relevant_rules = []
        
        # Define rule categories
        servo_kws = ['servo', 'attach', 'setperiodhertz']
        motor_kws = ['l298n', 'in1', 'in2', 'motor driver']
        weapon_kws = ['arming', 'disarm', 'fire', 'combat'] # Removed 'state machine' to prevent over-filtering
        button_kws = ['button', 'switch', 'debounce', 'digitalread', 'input_pullup']
        
        has_specific_context = hardware["servo"] or hardware["dc_motor"] or hardware["weapon"]
        has_specific_context = hardware["servo"] or hardware["dc_motor"] or hardware["weapon"] or hardware["button"]
        
        for rule in all_rules:
            rule_lower = rule.lower()
            
            is_servo_rule = any(w in rule_lower for w in servo_kws)
            is_motor_rule = any(w in rule_lower for w in motor_kws)
            is_weapon_rule = any(w in rule_lower for w in weapon_kws)
            is_button_rule = any(w in rule_lower for w in button_kws)
            
            # Pattern Over-application: Strict filtering
            if has_specific_context:
                if hardware["dc_motor"] and not hardware["servo"] and is_servo_rule: continue
                if hardware["servo"] and not hardware["dc_motor"] and is_motor_rule: continue
                if not hardware["weapon"] and is_weapon_rule: continue
                if not hardware["button"] and is_button_rule: continue
            
                # If question is about weapons (logic), EXCLUDE servo rules unless servo explicitly requested
                if hardware["weapon"] and not hardware["servo"] and is_servo_rule: continue
                
            else:
                # Generic context: Exclude all specific hardware rules
                if is_servo_rule or is_motor_rule or is_weapon_rule: continue
                if is_servo_rule or is_motor_rule or is_weapon_rule or is_button_rule: continue

            relevant_rules.append(rule)
        
        return relevant_rules

    def build_enhanced_prompt(self, user_message: str, hardware_detected: str = None) -> str:
        """Build prompt with FILTERED rules"""
        
        # Classify hardware
        hardware = self.classify_hardware(user_message)
        
        # Get ALL rules
        all_rules = self.get_all_rules()
        
        # Filter by relevance
        relevant_rules = self.filter_rules_by_hardware(all_rules, hardware)
        
        # Build focused prompt
        hardware_context = []
        if hardware["servo"]:
            hardware_context.append("SERVO CONTROL")
        if hardware["dc_motor"]:
            hardware_context.append("DC MOTOR CONTROL")
        if hardware["button"]: hardware_context.append("BUTTON INPUTS")
        if hardware["led"]: hardware_context.append("LED STATUS")
        if hardware["weapon"]: hardware_context.append("WEAPON SYSTEM")
        
        l298n_rules = ""
        if hardware["dc_motor"]:
            l298n_rules = """
- L298N WIRING RULES (MANDATORY):
  1. IN1/IN2 = Digital Output (Direction). Use digitalWrite().
  2. ENA = PWM Output (Speed). Use ledcWrite().
  3. To Move: IN1/IN2 must be OPPOSITE (HIGH/LOW).
  4. To Stop: IN1/IN2 both LOW.
  5. DO NOT treat Motors like Servos (No 'position' or 'angle').
- SAFETY RULES (MANDATORY):
  1. Implement a safety timeout (e.g., 5000ms).
  2. Stop motors if no signal is received within timeout.
  3. Use millis() for non-blocking timing.
"""

        weapon_rules = ""
        if hardware.get("weapon"):
            weapon_rules = """
- COMBAT PROTOCOL (MANDATORY):
  1. LOGIC FOCUS: This is a State Machine request, NOT just servo movement.
  2. STATES: enum State { DISARMED, ARMING, ARMED, FIRING };
  3. TRANSITIONS: DISARMED -> ARMING (2s delay) -> ARMED -> FIRING.
  4. SAFETY: Auto-disarm after 10s idle. Fire only when ARMED.
  5. STRUCTURE: Use switch(currentState) { case ... } for logic.
  6. OUTPUTS: Control relays/LEDs/Motors based on state.
"""

        # Anti-bloat rules
        anti_bloat_rules = []
        if not hardware["button"]:
            anti_bloat_rules.append("- NO EXTRA INPUTS: Do NOT add buttons, switches, or digitalRead() unless explicitly requested.")
            anti_bloat_rules.append("NO BUTTONS: Do NOT add digitalRead() or input pins.")
        if not hardware["servo"]:
            anti_bloat_rules.append("- NO EXTRA SERVOS: Do NOT add Servo objects or attach() unless explicitly requested.")
            anti_bloat_rules.append("NO SERVOS: Do NOT add Servo objects or attach().")
        if not hardware["dc_motor"]:
            anti_bloat_rules.append("- NO EXTRA MOTORS: Do NOT add motor driver code (L298N) unless explicitly requested.")
            anti_bloat_rules.append("NO MOTORS: Do NOT add motor driver code (L298N).")
        
        anti_bloat = "\n".join(anti_bloat_rules)
        anti_bloat = "\n".join([f"- {r}" for r in anti_bloat_rules])

        # Modularity rule
        modularity_rule = ""
        if "function" in user_message.lower() or "naming" in user_message.lower() or "modular" in user_message.lower():
            modularity_rule = """
- CODE STRUCTURE (MANDATORY):
  1. NO MONOLITHIC LOOP: Break code into small, descriptive functions.
  2. NAMING: Use camelCase for functions (e.g., readBatteryVoltage(), updateDisplay()).
  3. loop() must ONLY call these functions, not contain raw logic.
"""

        # Status LED rule
        status_led_rule = ""
        if hardware["led"] and ("status" in user_message.lower() or "indicator" in user_message.lower()):
            status_led_rule = """
- STATUS LED RULES (MANDATORY):
  1. NO BREATHING/FADING: Do not use simple PWM fading loops.
  2. USE STATES: Define enum LEDStatus { OFF, IDLE, ACTIVE, ERROR };
  3. IMPLEMENTATION: Create void setStatusLED(LEDStatus state).
  4. PATTERNS: IDLE=Slow Blink, ACTIVE=Solid On, ERROR=Fast Blink.
"""

        prompt = f"""You are generating code for: {', '.join(hardware_context)}
You are an expert embedded developer.
TARGET HARDWARE: {hardware_detected}
ACTIVE MODULES: {', '.join(hardware_context) if hardware_context else "None (Logic Only)"}

CRITICAL: Only use code patterns relevant to the hardware mentioned.
STRICT NEGATIVE CONSTRAINTS (DO NOT IGNORE):
{anti_bloat}

MANDATORY HARDWARE RULES:
{l298n_rules}
{weapon_rules}
{status_led_rule}
{anti_bloat}
{modularity_rule}

GENERAL GUIDELINES:
- If DC MOTOR: Use L298N patterns (digitalWrite, ledcWrite)
- If SERVO: Use ESP32Servo patterns (attach, write)
- DO NOT mix servo code into motor questions
- DO NOT mix motor code into servo questions

CRITICAL RULES (MUST FOLLOW):
{chr(10).join(relevant_rules)}

USER REQUEST:
{user_message}

Generate code following ALL rules above. Do not add unrequested features.
FINAL CHECK:
1. Did you add unrequested buttons? REMOVE THEM.
2. Did you add unrequested servos? REMOVE THEM.
3. Generate code ONLY for the hardware requested.
"""
        
        return prompt

    def teach_rule(self, rule_text: str):
        """Explicitly save a user-taught rule"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO code_rules 
            (rule_text, pattern_find, pattern_replace, confidence, learned_from)
            VALUES (?, ?, ?, ?, ?)
        """, (rule_text, "", "", 1.0, 'user_taught'))
        conn.commit()
        conn.close()

    def log_compilation_result(self, code: str, success: bool, errors: str = ""):
        """Track what compiles vs what fails"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compilation_log (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                code TEXT,
                success BOOLEAN,
                errors TEXT,
                hardware TEXT
            )
        """)
        
        cursor.execute("""
            INSERT INTO compilation_log 
            (timestamp, code, success, errors, hardware)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            code,
            success,
            errors,
            "ESP32-C3"  # Your target hardware
        ))
        
        conn.commit()
        conn.close()

    def is_simple_question(self, message: str) -> bool:
        """Check if this is a simple question that should use FAST model"""
        message_lower = message.lower()
        
        simple_triggers = [
            "what is", "what's", "who is", "who's", "when is",
            "how do i", "can you explain", "tell me about",
            "what are", "where is", "hi", "hello", "hey",
            "good morning", "good evening"
        ]
        
        # Also check if it's just a question without code keywords
        code_keywords = ["generate", "create", "write", "build", "code", "function"]
        
        has_simple_trigger = any(trigger in message_lower for trigger in simple_triggers)
        has_code_keyword = any(keyword in message_lower for keyword in code_keywords)
        
        # Simple if: has simple trigger AND no code keywords
        return has_simple_trigger and not has_code_keyword
    
    def is_complex(self, message: str) -> bool:
        """Check if request is too complex and should be broken down"""
        message_lower = message.lower()
        
        # Count complexity triggers
        trigger_count = sum(1 for trigger in COMPLEX_TRIGGERS if trigger in message_lower)
        
        # Count how many modules mentioned
        module_count = 0
        for module, keywords in MODULE_PATTERNS.items():
            # module is used for key, keywords for values
            if any(kw in message_lower for kw in keywords):
                module_count += 1
        
        # Complex if: multiple triggers OR 3+ modules mentioned
        return trigger_count >= 2 or module_count >= 3
        
    def extract_modules(self, message: str) -> List[str]:
        """Extract which modules are needed"""
        message_lower = message.lower()
        needed_modules = []
        
        for module, keywords in MODULE_PATTERNS.items():
            # module is used for key, keywords for values
            if any(kw in message_lower for kw in keywords):
                needed_modules.append(module)
                
        return needed_modules
        
    def build_modular_plan(self, modules: List[str]) -> List[Dict[str, str]]:
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
        
    def get_user_status(self) -> str:
        """Determine James's context based on defined schedule"""
        now = datetime.now()
        day = now.weekday() # 0=Mon, 6=Sun
        t = now.hour + (now.minute / 60.0)
        
        if day <= 4: # Mon-Fri
            if 5.5 <= t < 6.5:
                return "Early Morning Build Session 🌅 (5:30-6:30 AM)"
            elif 6.5 <= t < 17.0:
                return "Work Hours (Facilities Caretaker) 🏢"
            elif 17.0 <= t < 21.0:
                return "Evening Build Session 🌙 (5:00-9:00 PM)"
            else:
                return "Rest Time 💤"
        elif day == 5: # Saturday
            return "Weekend Freedom 🎨 (Creative Mode)"
        else: # Sunday
            if t < 21.0:
                return "Weekend Freedom 🎨 (Until 9 PM)"
            else:
                return "Rest Time 💤"

    def get_learned_rules(self) -> List[Dict]:
        """Retrieve high-confidence rules"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT rule_text, pattern_find, pattern_replace, confidence FROM code_rules WHERE confidence >= 0.8")
        rows = cursor.fetchall()
        conn.close()
        return [{"rule": r[0], "find": r[1], "replace": r[2], "confidence": r[3]} for r in rows]

    def call_model(self, model_name: str, message: str, stream: bool = False, system_task: bool = False) -> Union[str, Generator[str, None, None]]:
        """Call specified model"""
        try:
            messages = []
            
            if system_task:
                # Direct prompt, no history, no enhancement
                messages.append({"role": "user", "content": message})
            else:
                # Use enhanced prompt builder
                enhanced_prompt = self.build_enhanced_prompt(message, self.current_hardware)
                
                # Add conversation history (excluding old system messages)
                history = [m for m in self.context_messages[-5:] if m.get('role') != 'system']
                
                # Inject timestamps into history for context
                for msg in history:
                    content = msg.get('content', '')
                    ts = msg.get('timestamp')
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts)
                            content = f"[{dt.strftime('%H:%M')}] {content}"
                        except ValueError:
                            pass
                    messages.append({"role": msg['role'], "content": content})
                
                # Use enhanced prompt instead of raw user message
                if history and history[-1].get('content') == message:
                    messages[-1]['content'] = enhanced_prompt
                else:
                    messages.append({"role": "user", "content": enhanced_prompt})
            
            self.last_prompt_debug = json.dumps(messages, indent=2)
            
            body = {
                "model": MODELS[model_name],
                "messages": messages,
                "stream": stream,
                "options": {
                    "temperature": 0.0,  # Deterministic output
                    "top_p": 1.0,
                    "top_k": 1,
                    "num_ctx": 1024
                }
            }
            
            headers = {"Content-Type": "application/json"}
            json_body = json.dumps(body)
            
            # Retry logic for connection stability
            # Attempts: 0=Normal, 1=Retry/CPU Fallback, 2=Final Retry
            for attempt in range(3):
                conn = None
                try:
                    # Re-serialize body in case options changed (CPU fallback)
                    json_body = json.dumps(body)
                    
                    conn = OLLAMA_POOL.get_connection()
                    conn.request("POST", "/api/chat", json_body, headers)
                    response = conn.getresponse()
                    
                    if stream:
                        if response.status != 200:
                            error_text = response.read().decode('utf-8')
                            conn.close()
                            
                            # GPU OOM Detection -> CPU Fallback
                            if "CUDA" in error_text or "buffer" in error_text:
                                if "num_gpu" not in body["options"]:
                                    print("⚠️ GPU OOM detected. Switching to CPU mode...")
                                    body["options"]["num_gpu"] = 0 # Force CPU
                                    continue # Retry immediately

                            try:
                                err_msg = f"Error {response.status}: {json.loads(error_text).get('error', error_text)}"
                            except:
                                err_msg = f"Error {response.status}: {error_text}"
                            
                            if "num_gpu" in body["options"]:
                                err_msg += "\n\n(⚠️ CPU Mode also failed. System RAM might be full.)"
                            elif "CUDA" in err_msg or "buffer" in err_msg:
                                err_msg += "\n\n(⚠️ GPU Out of Memory. Retrying on CPU failed.)"
                                
                            return (x for x in [err_msg])

                        return self._stream_response(response, conn)
                    
                    if response.status == 200:
                        data = json.loads(response.read().decode('utf-8'))
                        OLLAMA_POOL.return_connection(conn)
                        return data.get("message", {}).get("content", "No response")
                    else:
                        error_text = response.read().decode('utf-8')
                        conn.close()
                        
                        # GPU OOM Detection -> CPU Fallback (Non-stream)
                        if "CUDA" in error_text or "buffer" in error_text:
                            if "num_gpu" not in body["options"]:
                                print("⚠️ GPU OOM detected. Switching to CPU mode...")
                                body["options"]["num_gpu"] = 0 # Force CPU
                                continue # Retry immediately

                        try:
                            err_msg = f"Error {response.status}: {json.loads(error_text).get('error', error_text)}"
                        except:
                            err_msg = f"Error {response.status}: {error_text}"
                        
                        if "num_gpu" in body["options"]:
                            err_msg += "\n\n(⚠️ CPU Mode also failed.)"
                        elif "CUDA" in err_msg or "buffer" in err_msg:
                            err_msg += "\n\n(⚠️ GPU Out of Memory.)"
                        return err_msg
                            
                except (http.client.NotConnected, BrokenPipeError, ConnectionResetError, socket.timeout) as e:
                    if conn: conn.close()
                    if attempt == 2: # Last attempt
                        return f"Error: Connection failed. {str(e)}"
                    continue # Retry
                except Exception as e:
                    if conn: conn.close()
                    return f"Error: {str(e)}"
                    
        except Exception as e:
            return f"Error: {str(e)}"

    def _stream_response(self, response, conn) -> Generator[str, None, None]:
        """Yield chunks from HTTP response"""
        fully_consumed = False
        has_content = False
        try:
            while True:
                line = response.readline()
                if not line: break
                try:
                    data = json.loads(line.decode('utf-8'))
                    if "message" in data:
                        content = data["message"].get("content", "")
                        if content: 
                            has_content = True
                            yield content
                    if data.get("done"): 
                        fully_consumed = True
                        break
                except: pass
        except Exception as e:
            yield f"\n[Stream Error: {str(e)}]"
        finally:
            if fully_consumed:
                OLLAMA_POOL.return_connection(conn)
            else:
                conn.close()
        
        if not has_content and not fully_consumed:
            yield "\n[Error: Empty response from Ollama. Check if model is loaded.]"
                
    def execute_modular_build(self, _: str, modules: List[str], plan: List[Dict[str, str]], forge_mode: str = "2") -> str:
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
                
                if self.server_mode:
                    choice = forge_mode
                else:
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
        
    def apply_style_signature(self, generated_code: str) -> str:
        """Refine generated code to match James's specific naming and safety patterns"""
        # Apply Hardware Profile Rules (ESP32-C3 default for now)
        generated_code = self.hardware_profile.apply_hardware_rules(generated_code, self.current_hardware)

        # Apply learned replacements (High Confidence Only)
        rules = self.get_learned_rules()
        for r in rules:
            if r['confidence'] >= 0.95 and r['find'] and r['replace']:
                # Simple safety check: don't replace if replacement contains spaces (likely a description)
                if ' ' not in r['replace']:
                    try:
                        generated_code = re.sub(r['find'], r['replace'], generated_code)
                    except re.error:
                        pass
        
        return generated_code

    def record_feedback(self, message_id: int, feedback: bool, comment: str = "") -> Optional[str]:
        """Learn from user feedback."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO feedback (message_id, positive, comment, timestamp)
            VALUES (?, ?, ?, ?)
        """, (message_id, feedback, comment, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        # Adjust confidence scores
        self.update_style_confidence(message_id, feedback)
        
        if not feedback:
            self.analyze_failure(message_id)
            return self.regenerate_response(message_id, comment)
        return None

    def regenerate_response(self, message_id: int, comment: str = "") -> str:
        """Regenerate a response, optionally considering feedback comment"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT session_id, id FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return "Error: Message not found."
            
        session_id, current_id = row
        
        cursor.execute(
            "SELECT content FROM messages WHERE session_id = ? AND id < ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (session_id, current_id)
        )
        user_row = cursor.fetchone()
        conn.close()
        
        if user_row:
            prompt = user_row[0]
            if comment:
                prompt += f"\n\n[Feedback: {comment}]"
            
            print(f"🔄 Regenerating: {prompt[:50]}...")
            return self.chat(prompt)
        return "Error: Original prompt not found."

    def analyze_failure(self, message_id: int) -> None:
        """Analyze why a message received negative feedback"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            print(f"\n⚠️  Negative Feedback on Message #{message_id}")
            print(f"   Content: {row[0][:100]}...")

    def update_style_confidence(self, message_id: int, positive: bool) -> None:
        """Adjust confidence of style preferences based on feedback."""
        # message_id and positive are currently unused
        # Placeholder for V4.0 learning loop
        pass

    def _route_request(self, user_message: str, force_model: Optional[str], forge_mode: str) -> str:
        """Route the request to the appropriate model or handler."""
        # Determine model based on complexity
        if force_model:
            model = force_model
            print(f"\n⚡ Using {model.upper()} model (forced)...")
            return self.call_model(model, user_message)
        elif self.is_complex(user_message):
            modules = self.extract_modules(user_message)
            plan = self.build_modular_plan(modules)
            print("\n" + "=" * 50)
            print("🎯 COMPLEX REQUEST DETECTED!")
            print(f"Modules needed: {', '.join(modules)}")
            print(f"Breaking into {len(plan)} manageable steps")
            print("=" * 50)
            return self.execute_modular_build(user_message, modules, plan, forge_mode)
        elif self.is_search_query(user_message):
            # This is a search query - query the database
            return self.search_repositories(user_message)
        elif self.is_simple_question(user_message):
            print("\n⚡ Using FAST model (simple question)...")
            # Don't force code generation prompt for simple greetings or definitions
            msg_lower = user_message.lower().strip()
            is_greeting = any(msg_lower.startswith(w) for w in ['hi', 'hello', 'hey', 'good morning', 'good evening']) and len(user_message.split()) < 6
            is_conceptual = any(msg_lower.startswith(w) for w in ['what is', "what's", 'explain', 'tell me about', 'who is', 'can you explain'])
            return self.call_model("fast", user_message, system_task=(is_greeting or is_conceptual))
        else:
            print("\n⚖️  Using BALANCED model...")
            return self.call_model("balanced", user_message)

    def chat_stream(self, user_message: str, force_model: Optional[str] = None, forge_mode: str = "2") -> Generator[str, None, None]:
        """Streaming version of chat"""
        
        
        # Intercept commands
        if user_message.strip().startswith('/'):
            yield self.handle_slash_command(user_message.strip())
            return

        # Detect Hardware Context
        detected_hw = self.hardware_profile.detect_hardware(user_message)
        if detected_hw:
            self.current_hardware = detected_hw

        style_context = self.retrieve_style_context(user_message)
        if style_context:
            self.context_messages.append({"role": "system", "content": style_context})

        user_msg_id = self.save_message("user", user_message)
        self.context_messages.append({"id": user_msg_id, "role": "user", "content": user_message, "timestamp": datetime.now().isoformat()})

        full_response = ""
        
        # Route and stream
        if force_model:
            iterator = self.call_model(force_model, user_message, stream=True)
        elif self.is_complex(user_message):
            # Complex builds are not streamed token-by-token in this version
            # We yield the final result as one chunk
            modules = self.extract_modules(user_message)
            plan = self.build_modular_plan(modules)
            result = self.execute_modular_build(user_message, modules, plan, forge_mode)
            iterator = [result]
        elif self.is_search_query(user_message):
            result = self.search_repositories(user_message)
            iterator = [result]
        elif self.is_simple_question(user_message):
            msg_lower = user_message.lower().strip()
            is_greeting = any(msg_lower.startswith(w) for w in ['hi', 'hello', 'hey', 'good morning', 'good evening']) and len(user_message.split()) < 6
            is_conceptual = any(msg_lower.startswith(w) for w in ['what is', "what's", 'explain', 'tell me about', 'who is', 'can you explain'])
            iterator = self.call_model("fast", user_message, stream=True, system_task=(is_greeting or is_conceptual))
        else:
            iterator = self.call_model("balanced", user_message, stream=True)
            
        for chunk in iterator:
            full_response += chunk
            yield chunk
            
        # Suggestions
        suggestions = self.shadow_engine.get_all_suggestions(user_message, full_response)
        if suggestions:
            bar = "\n\nPROACTIVE: > " + " ".join([f"{i+1}. {s}" for i, s in enumerate(suggestions)])
            full_response += bar
            yield bar
            
        msg_id = self.save_message("assistant", full_response)
        self.last_generated_id = msg_id
        self.context_messages.append({"id": msg_id, "role": "assistant", "content": full_response, "timestamp": datetime.now().isoformat()})

    def extract_code(self, text: str) -> List[str]:
        """Extract code blocks from markdown"""
        return re.findall(r'```(?:\w+)?\n(.*?)```', text, re.DOTALL)

    def handle_slash_command(self, command: str) -> str:
        """Handle slash commands when received via chat interface"""
        cmd = command.lower()
        
        if cmd.startswith('/teach'):
            rule = command[7:].strip()
            if rule:
                self.teach_rule(rule)
                return f"✅ Learned rule: {rule}"
            return "Usage: /teach <rule description>"
            
        if cmd.startswith('/correct'):
            reason = command[8:].strip()
            last_response = ""
            for msg in reversed(self.context_messages):
                if msg['role'] == 'assistant':
                    last_response = msg['content']
                    break
            if last_response:
                self.save_correction(last_response, "", reason)
                return "✅ Correction saved. (Run /learn to process patterns)"
            return "❌ No recent message to correct."

        if cmd == '/rules':
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT rule_text, confidence FROM code_rules ORDER BY confidence DESC")
            rows = cursor.fetchall()
            conn.close()
            if not rows: return "🤷 No rules learned yet."
            return "🧠 Learned Rules:\n" + "\n".join([f"- {r[0]}" for r in rows])

        if cmd == '/learn':
            patterns = self.learner.analyze_corrections(self)
            if patterns:
                return f"✅ Learned {len(patterns)} new rules:\n" + "\n".join([f"- {p['rule']}" for p in patterns])
            return "No new patterns found."

        if cmd == '/metrics':
            stats = self.metrics.calculate_accuracy()
            return (f"📊 Learning Metrics (Last 30 Days):\n"
                    f"   Accuracy:        {stats['accuracy']:.1f}%\n"
                    f"   Correction Rate: {stats['correction_rate']:.1f}%\n"
                    f"   Trend (7d):      {stats['improvement']}")

        if cmd == '/debug':
            if self.last_prompt_debug:
                return f"🐛 Last Prompt Sent:\n```json\n{self.last_prompt_debug}\n```"
            return "❌ No prompt sent yet."

        if cmd == '/validate':
            last_response = ""
            user_context = ""
            
            # Find last assistant message and preceding user message
            for i in range(len(self.context_messages) - 1, -1, -1):
                if self.context_messages[i]['role'] == 'assistant':
                    last_response = self.context_messages[i]['content']
                    if i > 0 and self.context_messages[i-1]['role'] == 'user':
                        user_context = self.context_messages[i-1]['content']
                    break
            
            if not last_response:
                return "❌ No recent code to validate."

            code_blocks = self.extract_code(last_response)
            if not code_blocks:
                return "❌ No code blocks found in last response."

            report = ["🔍 Validating last response..."]
            all_valid = True
            for i, code in enumerate(code_blocks, 1):
                valid, issues = self.validator.validate(code, self.current_hardware, user_context)
                if not valid:
                    all_valid = False
                    report.append(f"\nBlock {i} Issues:")
                    for issue in issues:
                        icon = "❌" if issue['severity'] == 'error' else "⚠️"
                        report.append(f"  {icon} Line {issue.get('line', '?')}: {issue['message']}")
                else:
                    report.append(f"✅ Block {i} is valid.")
            
            if all_valid:
                report.append("\n✨ All code blocks look good!")
            
            return "\n".join(report)

        if cmd == '/status':
            mem_usage = "N/A"
            if psutil:
                process = psutil.Process(os.getpid())
                mem_usage = f"{process.memory_info().rss / 1024 / 1024:.0f} MB"
            
            return (f"🖥️ System Status:\n"
                    f"   Session:  {self.session_id}\n"
                    f"   Hardware: {self.current_hardware}\n"
                    f"   Memory:   {mem_usage}\n"
                    f"   Messages: {len(self.context_messages)}")

        return f"Command {cmd.split()[0]} not supported in chat mode."


    # --- Main Chat Method ---
    def chat(self, user_message: str, force_model: Optional[str] = None, forge_mode: str = "2") -> str:
        """Main chat with smart routing and shadow suggestions"""
        
        # Intercept commands
        if user_message.strip().startswith('/'):
            return self.handle_slash_command(user_message.strip())

        # Detect Hardware Context
        detected_hw = self.hardware_profile.detect_hardware(user_message)
        if detected_hw:
            self.current_hardware = detected_hw
            print(f"🔧 Target Hardware Detected: {self.current_hardware}")

        style_context = self.retrieve_style_context(user_message)
        if style_context:
            self.context_messages.append({"role": "system", "content": style_context})

        user_msg_id = self.save_message("user", user_message)
        self.context_messages.append({"id": user_msg_id, "role": "user", "content": user_message, "timestamp": datetime.now().isoformat()})

        # Direct Schedule Check
        if "what should i be doing" in user_message.lower() or "my schedule" in user_message.lower() or "schedule check" in user_message.lower():
            status = self.get_user_status()
            response = f"📅 **Schedule Check**\nAccording to your protocol, you should be: **{status}**"
            print(f"⏰ Schedule check triggered: {status}")
            msg_id = self.save_message("assistant", response)
            self.last_generated_id = msg_id
            self.context_messages.append({"id": msg_id, "role": "assistant", "content": response, "timestamp": datetime.now().isoformat()})
            return response

        response = self._route_request(user_message, force_model, forge_mode)

        # Apply Style Guard
        response = self.apply_style_signature(response)
        
        # Extract code blocks
        code_blocks = self.extract_code(response)
        
        # Validate each code block
        for code in code_blocks:
            valid, issues = self.validator.validate(code, self.current_hardware, user_message)
            
            if not valid:
                # Auto-fix critical issues
                fixed_code = self.validator.auto_fix(code, issues)
                response = response.replace(code, fixed_code)
                
                # Sanitize explanation text based on fixes
                for issue in issues:
                    if "Debouncing detected" in issue['message']:
                        response = re.sub(r'(?i)(\*\*?Debouncing\*\*?:?|Debouncing)', r'~~\1~~ (Removed)', response)
                
                # Append explanation
                response += "\n\n⚠️  **Auto-corrected:**\n"
                for issue in issues:
                    if issue['severity'] == 'error':
                        response += f"- {issue['message']}\n"
        
        # Generate Suggestion Bar
        suggestions = self.shadow_engine.get_all_suggestions(user_message, response)
        if suggestions:
            bar = "\n\nPROACTIVE: > " + " ".join([f"{i+1}. {s}" for i, s in enumerate(suggestions)])
            response += bar

        msg_id = self.save_message("assistant", response)
        self.last_generated_id = msg_id
        self.context_messages.append({"id": msg_id, "role": "assistant", "content": response, "timestamp": datetime.now().isoformat()})

        return response
        
    def get_sessions(self, limit: int = 20) -> List[Dict[str, str]]:
        """Retrieve recent sessions from DB"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT session_id, started_at, title FROM sessions WHERE user_id = ? ORDER BY started_at DESC LIMIT ?", (self.user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "date": r[1], "title": r[2] if len(r) > 2 else None} for r in rows]

    def rename_session(self, session_id: str, new_title: str) -> None:
        """Rename a session"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET title = ? WHERE session_id = ? AND user_id = ?", (new_title, session_id, self.user_id))
        conn.commit()
        conn.close()

    def delete_session(self, session_id: str) -> None:
        """Delete a session and its messages"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_id = ? AND user_id = ?", (session_id, self.user_id))
        if cursor.rowcount > 0:
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def clear_current_session(self) -> None:
        """Clear all messages from the current session"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
        conn.commit()
        conn.close()
        self.context_messages = []

    def load_session(self, session_id: str) -> List[Dict[str, str]]:
        """Load a specific session context"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT 1 FROM sessions WHERE session_id = ? AND user_id = ?", (session_id, self.user_id))
        if not cursor.fetchone():
            conn.close()
            return []
            
        cursor.execute("SELECT id, role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
        rows = cursor.fetchall()
        conn.close()
        
        self.session_id = session_id
        self.context_messages = []
        loaded_history = []
        for msg_id, role, content, ts in rows:
            msg = {"id": msg_id, "role": role, "content": content, "timestamp": ts}
            self.context_messages.append(msg)
            loaded_history.append(msg)
        return loaded_history

    def start_new_session(self) -> str:
        """Reset context and start new session"""
        self.session_id = self.create_session()
        self.context_messages = []
        return self.session_id

    def reset_gpu(self) -> str:
        """Force unload models from GPU to free VRAM"""
        try:
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=10)
            # Unload all known models
            for model in MODELS.values():
                body = json.dumps({"model": model, "keep_alive": 0})
                conn.request("POST", "/api/generate", body)
                resp = conn.getresponse()
                resp.read() # Consume response
            conn.close()
            return "✅ GPU Memory Cleared (Models Unloaded)"
        except Exception as e:
            return f"❌ Error clearing GPU: {str(e)}"

    def export_session_to_markdown(self, session_id: str = None) -> str:
        """Export session history to a Markdown file"""
        sid = session_id or self.session_id
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id ASC", (sid,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "No history found."
            
        filename = f"session_{sid}.md"
        filepath = DATA_DIR / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# BuddAI Session: {sid}\n\n")
            for role, content, ts in rows:
                f.write(f"### {role.upper()} ({ts})\n\n{content}\n\n---\n\n")
                
        return f"✅ Session exported to: {filepath}"

    def get_session_export_data(self, session_id: str = None) -> Dict:
        """Get session data as a dictionary for export"""
        sid = session_id or self.session_id
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id ASC", (sid,))
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "session_id": sid,
            "exported_at": datetime.now().isoformat(),
            "messages": [{"role": r, "content": c, "timestamp": t} for r, c, t in rows]
        }

    def export_session_to_json(self, session_id: str = None) -> str:
        """Export session history to a JSON file"""
        data = self.get_session_export_data(session_id)
        if not data["messages"]:
            return "No history found."
            
        filename = f"session_{data['session_id']}.json"
        filepath = DATA_DIR / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
                
        return f"✅ Session exported to: {filepath}"

    def import_session_from_json(self, data: Dict) -> str:
        """Import a session from JSON data"""
        session_id = data.get("session_id")
        messages = data.get("messages", [])
        
        if not session_id or not messages:
            raise ValueError("Invalid session JSON format")
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if session exists to avoid collision
        cursor.execute("SELECT 1 FROM sessions WHERE session_id = ? AND user_id = ?", (session_id, self.user_id))
        if cursor.fetchone():
            # Generate new ID
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_id = f"{session_id}_imp_{timestamp}"
        
        # Determine start time
        started_at = datetime.now().isoformat()
        if messages and "timestamp" in messages[0]:
            started_at = messages[0]["timestamp"]
            
        cursor.execute(
            "INSERT INTO sessions (session_id, user_id, started_at, title) VALUES (?, ?, ?, ?)",
            (session_id, self.user_id, started_at, f"Imported: {data.get('session_id')}")
        )
        
        # Insert messages
        for msg in messages:
            cursor.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, msg.get("role"), msg.get("content"), msg.get("timestamp", datetime.now().isoformat()))
            )
            
        conn.commit()
        conn.close()
        
        return session_id

    def create_backup(self) -> Tuple[bool, str]:
        """Create a safe backup of the database"""
        if not DB_PATH.exists():
            return False, "Database file not found."
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"conversations_{timestamp}.db"
        
        try:
            # Use SQLite backup API for consistency
            src = sqlite3.connect(DB_PATH)
            dst = sqlite3.connect(backup_path)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
            return True, str(backup_path)
        except Exception as e:
            return False, str(e)

    def run(self) -> None:
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
                        print("/learn - Extract patterns from corrections")
                        print("/analyze - Analyze session for implicit feedback")
                        print("/correct <reason> - Mark previous response wrong")
                        print("/good - Mark previous response correct")
                        print("/teach <rule> - Explicitly teach a rule")
                        print("/validate - Re-validate last response")
                        print("/rules - Show learned rules")
                        print("/metrics - Show improvement stats")
                        print("/train - Export corrections for fine-tuning")
                        print("/save - Export chat to Markdown")
                        print("/backup - Backup database")
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
                    elif cmd == '/learn':
                        print("🧠 Analyzing corrections for patterns...")
                        patterns = self.learner.analyze_corrections(self)
                        if patterns:
                            print(f"✅ Learned {len(patterns)} new rules:")
                            for p in patterns:
                                print(f"  - {p['rule']}")
                        else:
                            print("No new patterns found.")
                        continue
                    elif cmd == '/analyze':
                        self.adaptive_learner.learn_from_session(self.session_id)
                        continue
                    elif cmd.startswith('/correct'):
                        reason = user_input[8:].strip()
                        last_response = ""
                        # Find last assistant message
                        for msg in reversed(self.context_messages):
                            if msg['role'] == 'assistant':
                                last_response = msg['content']
                                break
                        self.save_correction(last_response, "", reason)
                        print("✅ Correction saved. Run /learn to process it.")
                        continue
                    elif cmd == '/good':
                        if self.last_generated_id:
                            self.record_feedback(self.last_generated_id, True)
                            print("✅ Feedback recorded: Positive")
                        else:
                            print("❌ No recent message to rate.")
                        continue
                    elif cmd.startswith('/teach'):
                        rule = user_input[7:].strip()
                        if rule:
                            self.teach_rule(rule)
                            print(f"✅ Learned rule: {rule}")
                        else:
                            print("Usage: /teach <rule description>")
                        continue
                    elif cmd == '/validate':
                        last_response = ""
                        user_context = ""
                        
                        # Find last assistant message and preceding user message
                        for i in range(len(self.context_messages) - 1, -1, -1):
                            if self.context_messages[i]['role'] == 'assistant':
                                last_response = self.context_messages[i]['content']
                                if i > 0 and self.context_messages[i-1]['role'] == 'user':
                                    user_context = self.context_messages[i-1]['content']
                                break
                        
                        if not last_response:
                            print("❌ No recent code to validate.")
                            continue

                        code_blocks = self.extract_code(last_response)
                        if not code_blocks:
                            print("❌ No code blocks found in last response.")
                            continue

                        print("\n🔍 Validating last response...")
                        all_valid = True
                        for i, code in enumerate(code_blocks, 1):
                            valid, issues = self.validator.validate(code, self.current_hardware, user_context)
                            if not valid:
                                all_valid = False
                                print(f"\nBlock {i} Issues:")
                                for issue in issues:
                                    icon = "❌" if issue['severity'] == 'error' else "⚠️"
                                    print(f"  {icon} Line {issue.get('line', '?')}: {issue['message']}")
                            else:
                                print(f"✅ Block {i} is valid.")
                        
                        if all_valid:
                            print("\n✨ All code blocks look good!")
                        continue
                    elif cmd == '/rules':
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute("SELECT rule_text, confidence, learned_from FROM code_rules ORDER BY confidence DESC")
                        rows = cursor.fetchall()
                        conn.close()
                        
                        if not rows:
                            print("🤷 No rules learned yet.")
                        else:
                            print(f"\n🧠 Learned Rules ({len(rows)}):")
                            for rule, conf, source in rows:
                                print(f"  - [{conf:.1f}] {rule} ({source})")
                        continue
                    elif cmd == '/metrics':
                        stats = self.metrics.calculate_accuracy()
                        print("\n📊 Learning Metrics (Last 30 Days):")
                        print(f"   Accuracy:        {stats['accuracy']:.1f}%")
                        print(f"   Correction Rate: {stats['correction_rate']:.1f}%")
                        print(f"   Trend (7d):      {stats['improvement']}")
                        print("")
                        continue
                    elif cmd == '/debug':
                        if self.last_prompt_debug:
                            print(f"\n🐛 Last Prompt Sent:\n{self.last_prompt_debug}\n")
                        else:
                            print("❌ No prompt sent yet.")
                        continue
                    elif cmd == '/train':
                        result = self.fine_tuner.prepare_training_data()
                        print(f"✅ {result}")
                        continue
                    elif cmd == '/backup':
                        success, msg = self.create_backup()
                        if success:
                            print(f"✅ Database backed up to: {msg}")
                        else:
                            print(f"❌ Backup failed: {msg}")
                        continue
                    elif cmd.startswith('/save'):
                        if 'json' in user_input.lower():
                            print(self.export_session_to_json())
                        else:
                            print(self.export_session_to_markdown())
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



class ModelFineTuner:
    """Fine-tune local model on YOUR corrections"""
    
    def prepare_training_data(self):
        """Convert corrections to training format"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT original_code, corrected_code, reason 
            FROM corrections
        """)
        
        training_data = []
        for original, corrected, reason in cursor.fetchall():
            training_data.append({
                "prompt": f"Generate code for: {reason}",
                "completion": corrected,
                "negative_example": original
            })
        
        conn.close()
        
        # Save as JSONL for fine-tuning
        output_path = DATA_DIR / 'training_data.jsonl'
        with open(output_path, 'w', encoding='utf-8') as f:
            for item in training_data:
                f.write(json.dumps(item) + '\n')
        return f"Exported {len(training_data)} examples to {output_path}"
    
    def fine_tune_model(self):
        """Fine-tune Qwen on your corrections"""
        # This requires:
        # 1. Export training data
        # 2. Use Ollama modelfile or external training
        # 3. Create custom model: qwen2.5-coder-james:3b
        pass
