#!/usr/bin/env python3
"""
BuddAI Executive v3.1 - Modular Builder
BuddAI Executive v3.2 - Hardened Modular Builder
BuddAI Executive v3.3 - Advanced Modular Builder
BuddAI Executive v3.4 - Proactive Suggestion Engine
BuddAI Executive v3.5 - Adaptive Learning & Feedback
BuddAI Executive v3.6 - Modular API & Web UI
BuddAI Executive v3.7 - Secure Uploads & Session Export
BuddAI Executive v3.8 - Multi-User & Fine-Tuning Ready

Breaks complex tasks into manageable chunks

Author: James Gilbert
License: MIT
"""

import sys
import os
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import http.client
import re # noqa: F401
from typing import Optional, List, Dict, Tuple, Union, Generator
import zipfile
import shutil
import queue
import socket
import argparse
import io
import difflib
from urllib.parse import urlparse

try:
    import qrcode
except ImportError:
    qrcode = None

try:
    import psutil
except ImportError:
    psutil = None

# Server dependencies
try:
    from fastapi import FastAPI, UploadFile, File, Header, WebSocket, WebSocketDisconnect, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from pydantic import BaseModel
    import uvicorn
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

# Configuration
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "conversations.db"

# Validation Config
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_UPLOAD_FILES = 10
ALLOWED_TYPES = [
    "application/zip", "application/x-zip-compressed", "application/octet-stream",
    "text/plain", "text/x-python", "text/javascript", "application/javascript",
    "text/html", "text/css", "text/x-c", "text/x-c++src"
]

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

# --- Connection Pooling ---
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
class ShadowSuggestionEngine:
    """Proactively suggests modules/settings based on user/project history."""
    def __init__(self, db_path: Path, user_id: str = "default"):
        self.db_path = db_path
        self.user_id = user_id

    def lookup_recent_module_usage(self, module: str, limit: int = 5) -> List[Tuple[str, str, str]]:
        """Look up recent usage patterns for a module from repo_index."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT file_path, content, last_modified FROM repo_index
            WHERE (function_name LIKE ? OR file_path LIKE ?) AND user_id = ?
            ORDER BY last_modified DESC LIMIT ?
            """,
            (f"%{module}%", f"%{module}%", self.user_id, limit)
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def suggest_for_module(self, module: str) -> Optional[str]:
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

    def get_proactive_suggestion(self, user_input: str) -> Optional[str]:
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
            cursor.execute("SELECT content FROM repo_index WHERE content LIKE ? AND user_id = ? LIMIT 10", (f"%{module}%", self.user_id))
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

    def get_all_suggestions(self, user_input: str, generated_code: str) -> List[str]:
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


class SmartLearner:
    """Extract patterns from corrections"""
    
    def analyze_corrections(self, ai_interface=None):
        """Find common patterns in your fixes"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Ensure processed column exists
        try:
            cursor.execute("ALTER TABLE corrections ADD COLUMN processed BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Check pending count
        cursor.execute("SELECT COUNT(*) FROM corrections WHERE processed IS NOT 1")
        pending_count = cursor.fetchone()[0]

        if pending_count == 0:
            conn.close()
            return []

        # Process in small batches
        cursor.execute("""
            SELECT id, original_code, corrected_code, reason 
            FROM corrections
            WHERE processed IS NOT 1
            LIMIT 5
        """)
        
        corrections = cursor.fetchall()
        print(f"   Processing {len(corrections)} of {pending_count} pending corrections...")
        patterns = []
        
        for row_id, original, corrected, reason in corrections:
            # Strategy 1: Diff based (if corrected code exists)
            if corrected and original:
                # Extract what changed
                diff = self.diff_code(original, corrected)
                
                # Classify the change
                if "analogWrite" in original and "ledcWrite" in corrected:
                    patterns.append({
                        "rule": "ESP32 uses ledcWrite not analogWrite",
                        "find": "analogWrite",
                        "replace": "ledcWrite",
                        "hardware": "ESP32",
                        "confidence": 1.0
                    })
                
                if "delay(" in original and "millis()" in corrected:
                    patterns.append({
                        "rule": "Use non-blocking millis() not delay()",
                        "find": "delay\\(",
                        "replace": "millis() based timing",
                        "confidence": 0.9
                    })

            # Strategy 2: Reason based (LLM extraction)
            if reason and ai_interface:
                print(f"   - Analyzing #{row_id}...", end="\r")
                # Use LLM to extract rule from text reason
                prompt = f"""Analyze this correction text and extract specific technical coding rules.
                Ignore conversational filler.
                
                Correction Text:
                "{reason}"
                
                Return ONLY a list of rules in this format:
                Rule: <concise technical rule>
                """
                try:
                    response = ai_interface.call_model("fast", prompt, system_task=True)
                    for line in response.splitlines():
                        clean_line = line.strip().replace("**", "").replace("__", "")
                        rule_text = None
                        if "rule:" in clean_line.lower():
                            parts = clean_line.split(":", 1)
                            rule_text = parts[1].strip() if len(parts) > 1 else clean_line
                        elif re.match(r'^[\d-]+\.', clean_line) or clean_line.startswith("- "):
                            rule_text = re.sub(r'^[\d-]+\.?\s*', '', clean_line).strip()
                            
                        if rule_text and len(rule_text) > 10 and rule_text != reason:
                            patterns.append({
                                "rule": rule_text,
                                "find": "",
                                "replace": "",
                                "confidence": 0.85
                            })
                except Exception:
                    pass
            
            # Mark as processed immediately
            cursor.execute("UPDATE corrections SET processed = 1 WHERE id = ?", (row_id,))
            conn.commit()
        
        print("   - Batch complete.                          ")
        conn.close()

        # Store learned rules
        if patterns:
            self.save_rules(patterns)
            
        return patterns
    
    def save_rules(self, patterns):
        """Save to code_rules table"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
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
        
        for p in patterns:
            cursor.execute("""
                INSERT OR REPLACE INTO code_rules 
                (rule_text, pattern_find, pattern_replace, confidence, learned_from)
                VALUES (?, ?, ?, ?, ?)
            """, (p['rule'], p['find'], p['replace'], p['confidence'], 'corrections'))
        
        conn.commit()
        conn.close()

    def diff_code(self, original: str, corrected: str) -> str:
        """Generate a simple diff"""
        return "\n".join(difflib.unified_diff(
            original.splitlines(), 
            corrected.splitlines(), 
            fromfile='original', 
            tofile='corrected', 
            lineterm=''
        ))


class HardwareProfile:
    """Learn hardware-specific patterns"""
    
    ESP32_PATTERNS = {
        "pwm_setup": {
            "correct": "ledcSetup(channel, freq, resolution)",
            "wrong": ["analogWrite", "pwmWrite"],
            "learned_from": "James's corrections"
        },
        "serial_baud": {
            "preferred": 115200,
            "alternatives": [9600, 57600],
            "confidence": 1.0
        },
        "safety_timeout": {
            "standard": 5000,
            "pattern": "millis() - lastTime > TIMEOUT",
            "confidence": 1.0
        }
    }
    
    HARDWARE_KEYWORDS = {
        "ESP32-C3": ["esp32", "esp32c3", "c3", "esp-32"],
        "Arduino Uno": ["uno", "arduino uno", "atmega328p"],
        "Raspberry Pi Pico": ["pico", "rp2040"]
    }

    def detect_hardware(self, message: str) -> Optional[str]:
        msg_lower = message.lower()
        for hw, keywords in self.HARDWARE_KEYWORDS.items():
            if any(k in msg_lower for k in keywords):
                return hw
        return None
    
    def apply_hardware_rules(self, code: str, hardware: str) -> str:
        """Apply known hardware patterns"""
        if hardware == "ESP32-C3":
            # Apply ESP32-specific fixes
            code = self.fix_pwm(code)
            code = self.fix_serial(code)
            code = self.add_safety(code)
        return code

    def fix_pwm(self, code: str) -> str:
        for wrong in self.ESP32_PATTERNS["pwm_setup"]["wrong"]:
            if wrong in code:
                if wrong == "analogWrite":
                    code = code.replace("analogWrite", "ledcWrite")
        return code

    def fix_serial(self, code: str) -> str:
        preferred = self.ESP32_PATTERNS["serial_baud"]["preferred"]
        return re.sub(r'Serial\.begin\(\s*\d+\s*\)', f'Serial.begin({preferred})', code)

    def add_safety(self, code: str) -> str:
        if "motor" in code.lower() and "millis()" not in code:
             code += "\n// [BuddAI Safety] Warning: No non-blocking timeout detected. Consider adding safety timeout."
        return code


class CodeValidator:
    """Validate generated code before showing to user"""
    
    def find_line(self, code: str, substring: str) -> int:
        for i, line in enumerate(code.splitlines(), 1):
            if substring in line:
                return i
        return -1

    def has_safety_timeout(self, code: str) -> bool:
        # Simple heuristic: needs millis, subtraction, and a comparison to a value/constant
        # We want to avoid matching debounce logic (usually < 100ms)
        if "millis()" not in code: return False
        
        # Check for constants like SAFETY_TIMEOUT, MOTOR_TIMEOUT
        if re.search(r'>\s*[A-Z_]*TIMEOUT', code):
            return True
            
        # Check for state machine timeout (Combat Protocol)
        if "DISARM" in code and "millis" in code and ">" in code:
            return True
            
        # Check for numeric literals > 500 (Debounce is usually 50)
        comparisons = re.findall(r'>\s*(\d+)', code)
        return any(int(val) > 500 for val in comparisons)

    def matches_style(self, code: str) -> bool:
        # Placeholder for style matching logic
        return True

    def apply_style(self, code: str) -> str:
        # Placeholder for style application
        return code

    def refactor_loop_to_function(self, code: str) -> str:
        """Extract loop body into runSystemLogic()"""
        loop_match = re.search(r'void\s+loop\s*\(\s*\)\s*\{', code)
        if not loop_match: return code
        
        start_idx = loop_match.end()
        brace_count = 1
        loop_body_end = -1
        
        for i, char in enumerate(code[start_idx:], start=start_idx):
            if char == '{': brace_count += 1
            elif char == '}': brace_count -= 1
            
            if brace_count == 0:
                loop_body_end = i
                break
        
        if loop_body_end == -1: return code
        
        body = code[start_idx:loop_body_end]
        new_code = code[:start_idx] + "\n  runSystemLogic();\n" + code[loop_body_end:]
        new_code += "\n\nvoid runSystemLogic() {" + body + "}\n"
        return new_code

    def validate(self, code: str, hardware: str, user_message: str = "") -> Tuple[bool, List[Dict]]:
        """Check code against known rules"""
        issues = []
        
        # Check 1: ESP32 PWM
        if "ESP32" in hardware.upper():
            if "analogWrite" in code:
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, "analogWrite"),
                    "message": "ESP32 doesn't support analogWrite(). Use ledcWrite()",
                    "fix": lambda c: c.replace("analogWrite", "ledcWrite")
                })
        
        # Check 2: Non-blocking code
        if "delay(" in code and "motor" in code.lower():
            issues.append({
                "severity": "warning",
                "line": self.find_line(code, "delay"),
                "message": "Using delay() in motor code blocks safety checks",
                "fix": lambda c: c # No auto-fix
            })
        
        # Check 3: Safety timeout
        if ("motor" in code.lower() or "servo" in code.lower()):
            if not self.has_safety_timeout(code):
                issues.append({
                    "severity": "error",
                    "message": "Critical: No safety timeout detected (must be > 500ms).",
                    "fix": lambda c: "#define SAFETY_TIMEOUT 5000\nunsigned long lastCommand = 0;\n" + \
                                     re.sub(r'(void\s+loop\s*\(\s*\)\s*\{)', \
                                            r'\1\n  // [AUTO-FIX] Safety Timeout\n  if (millis() - lastCommand > SAFETY_TIMEOUT) {\n    // STOP MOTORS\n    ledcWrite(0, 0);\n    ledcWrite(1, 0);\n  }\n', c)
                })
        
        # Check 4: L298N PWM Pin Misuse
        pwm_pins = re.findall(r'ledcAttachPin\s*\(\s*(\w+)\s*,', code)
        for pin in pwm_pins:
            # Check if digitalWrite is used on this pin
            if re.search(r'digitalWrite\s*\(\s*' + re.escape(pin) + r'\s*,', code):
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, f"digitalWrite({pin}"),
                    "message": f"Conflict: PWM pin '{pin}' used with digitalWrite(). Use ledcWrite() for speed control.",
                    "fix": lambda c, p=pin: re.sub(r'digitalWrite\s*\(\s*' + re.escape(p) + r'\s*,\s*[^)]+\);?', f'// [Fixed] Removed conflicting digitalWrite on PWM pin {p}', c)
                })

        # Check 5: Broken Debounce Logic (Type Mismatch)
        # Example: if (buttonState != lastDebounceTime)
        bad_debounce = re.search(r'if\s*\(\s*\w+\s*[!=]=\s*\w*DebounceTime\s*\)', code)
        if bad_debounce:
            issues.append({
                "severity": "error",
                "line": self.find_line(code, bad_debounce.group(0)),
                "message": "Type Mismatch: Comparing button state (int) with time (long).",
                "fix": lambda c: c.replace(bad_debounce.group(0), "if ((millis() - lastDebounceTime) > debounceDelay)")
            })

        # Check 6: Safety Timeout Value
        timeout_match = re.search(r'#define\s+SAFETY_TIMEOUT\s+(\d+)', code)
        if timeout_match and int(timeout_match.group(1)) > 5000:
            issues.append({
                "severity": "error",
                "line": self.find_line(code, timeout_match.group(0)),
                "message": f"Safety timeout {timeout_match.group(1)}ms is too long (Max: 5000ms).",
                "fix": lambda c: re.sub(r'(#define\s+SAFETY_TIMEOUT\s+)\d+', r'\g<1>5000', c)
            })

        # Check 7: Broken Safety Timer Logic (Static Init)
        bad_static = re.search(r'static\s+unsigned\s+long\s+(\w+)\s*=\s*millis\(\);', code)
        if bad_static:
            issues.append({
                "severity": "error",
                "line": self.find_line(code, bad_static.group(0)),
                "message": "Static timer initialized with millis() prevents reset. Initialize to 0.",
                "fix": lambda c: c.replace(bad_static.group(0), f"static unsigned long {bad_static.group(1)} = 0;")
            })

        # Check 8: Incomplete Motor Logic (L298N Validation)
        # If user explicitly asks for L298N or DC Motor, OR asks for 'motor' without 'servo'
        is_l298n_request = "l298n" in user_message.lower() or "dc motor" in user_message.lower() or ("motor" in user_message.lower() and "servo" not in user_message.lower())
        
        if is_l298n_request:
            # 1. Check for Direction Pins (IN1/IN2)
            if not re.search(r'(?:#define|const\s+int)\s+\w*(?:IN1|IN2|DIR)\w*', code, re.IGNORECASE):
                issues.append({
                    "severity": "error",
                    "message": "Missing L298N Direction Pins (IN1/IN2).",
                    "fix": lambda c: "// [AUTO-FIX] L298N Definitions\n#define IN1 18\n#define IN2 19\n" + c
                })

            # 2. Check for PWM Pin (ENA)
            if not re.search(r'(?:#define|const\s+int)\s+\w*(?:ENA|ENB|PWM)\w*', code, re.IGNORECASE):
                issues.append({
                    "severity": "error",
                    "message": "Missing L298N PWM Pin (ENA).",
                    "fix": lambda c: "#define ENA 21 // [AUTO-FIX] Missing PWM Pin\n" + c
                })

            # 3. Check for Direction Control (digitalWrite)
            if "digitalWrite" not in code:
                issues.append({
                    "severity": "error",
                    "message": "L298N requires digitalWrite() for direction control.",
                    "fix": lambda c: re.sub(r'(void\s+loop\s*\(\s*\)\s*\{)', r'\1\n  // [AUTO-FIX] Set Direction\n  digitalWrite(IN1, HIGH);\n  digitalWrite(IN2, LOW);\n', c)
                })

        # Check 9: Unnecessary Wire.h
        wire_include = re.search(r'#include\s+[<"]Wire\.h[>"]', code)
        if wire_include:
            # Check if Wire is actually used (excluding the include itself)
            rest_of_code = code.replace(wire_include.group(0), "")
            if not re.search(r'\bWire\b', rest_of_code):
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, wire_include.group(0)),
                    "message": "Unnecessary #include <Wire.h> detected.",
                    "fix": lambda c: re.sub(r'#include\s+[<"]Wire\.h[>"]', '// [Auto-Fix] Removed unnecessary Wire.h', c)
                })

        # Check 10: High-Frequency Serial Logging
        if ("Serial.print" in code or "Serial.write" in code) and \
           ("motor" in code.lower() or "servo" in code.lower()):
            # Check for throttling pattern (simple heuristic for timer variables)
            if not re.search(r'(print|log|debug|serial)\s*Timer', code, re.IGNORECASE) and \
               not re.search(r'last\s*(Print|Log|Debug)', code, re.IGNORECASE):
                issues.append({
                    "severity": "warning",
                    "line": self.find_line(code, "Serial.print"),
                    "message": "Serial logging in motor loops causes jitter. Ensure it's throttled (e.g. every 100ms).",
                    "fix": lambda c: c + "\n// [Performance] Warning: Serial.print() inside loops can interrupt motor timing."
                })

        # Check 11: Feature Bloat (Unrequested Button)
        if user_message:
            msg_lower = user_message.lower()
            # If user didn't ask for inputs/buttons
            if not any(w in msg_lower for w in ['button', 'switch', 'input', 'trigger']):
                # Pattern 1: Variable assignment (int btn = digitalRead(...))
                for match in re.finditer(r'(?:int|bool|byte)\s+(\w*(?:button|btn|switch)\w*)\s*=\s*digitalRead\s*\([^;]+;', code, re.IGNORECASE):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": f"Feature Bloat: Unrequested button code detected ('{match.group(1)}').",
                        "fix": lambda c, m=match.group(0): c.replace(m, "")
                    })
                
                # Pattern 2: Direct usage in conditions (if (digitalRead(BUTTON_PIN)...))
                for match in re.finditer(r'digitalRead\s*\(\s*(\w*(?:BUTTON|BTN|SWITCH)\w*)\s*\)', code, re.IGNORECASE):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": f"Feature Bloat: Unrequested button check detected ('{match.group(1)}').",
                        "fix": lambda c, m=match.group(0): c.replace(m, "0")
                    })
                
                # Pattern 3: pinMode(..., INPUT)
                for match in re.finditer(r'pinMode\s*\(\s*\w+\s*,\s*INPUT(?:_PULLUP)?\s*\);', code):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": "Feature Bloat: Unrequested input pin configuration.",
                        "fix": lambda c, m=match.group(0): c.replace(m, "")
                    })
                
                # Pattern 4: Unused button variable initialization (int btn = LOW;)
                for match in re.finditer(r'(?:int|bool|byte)\s+(\w*(?:button|btn|switch)\w*)\s*=\s*(?:LOW|HIGH|0|1|false|true)\s*;', code, re.IGNORECASE):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": f"Feature Bloat: Unused button variable '{match.group(1)}'.",
                        "fix": lambda c, m=match.group(0): c.replace(m, "")
                    })

        # Check 14: State Machine for Weapons (Combat Protocol)
        if "weapon" in user_message.lower() or "combat" in user_message.lower() or "state machine" in user_message.lower():
            if "enum" not in code and "bool isArmed" not in code:
                 issues.append({
                    "severity": "error",
                    "message": "Combat code requires a State Machine (enum State or bool isArmed).",
                    "fix": lambda c: c.replace("void setup", "\n// [AUTO-FIX] State Machine\nenum State { DISARMED, ARMING, ARMED, FIRING };\nState currentState = DISARMED;\nunsigned long stateTimer = 0;\n\nvoid setup") if "void setup" in c else "// [AUTO-FIX] State Machine\nenum State { DISARMED, ARMING, ARMED, FIRING };\nState currentState = DISARMED;\n" + c
                })
            
            if "Serial.read" not in code and "Serial.available" not in code:
                 issues.append({
                    "severity": "error",
                    "message": "Missing Serial Command handling (e.g., 'A' to Arm).",
                    "fix": lambda c: c.replace("void loop() {", "void loop() {\n  if (Serial.available()) {\n    char cmd = Serial.read();\n    // Handle commands\n  }\n")
                })

        # Check 15: Function Naming Conventions (camelCase)
        # Exclude standard Arduino functions
        func_defs = re.finditer(r'\b(void|int|bool|float|double|String|char|long|unsigned(?:\s+long)?)\s+([a-zA-Z0-9_]+)\s*\(', code)
        for match in func_defs:
            func_name = match.group(2)
            if func_name in ['setup', 'loop', 'main']: continue
            
            # Check if camelCase (starts with lowercase, no underscores unless specific style)
            if not re.match(r'^[a-z][a-zA-Z0-9]*$', func_name):
                # Check if it's snake_case or PascalCase
                suggestion = func_name
                if '_' in func_name: # snake_case -> camelCase
                    components = func_name.split('_')
                    suggestion = components[0].lower() + ''.join(x.title() for x in components[1:])
                elif func_name[0].isupper(): # PascalCase -> camelCase
                    suggestion = func_name[0].lower() + func_name[1:]
                
                issues.append({
                    "severity": "warning",
                    "line": self.find_line(code, match.group(0)),
                    "message": f"Style: Function '{func_name}' should be camelCase (e.g., '{suggestion}').",
                    "fix": lambda c, old=func_name, new=suggestion: c.replace(old, new)
                })

        # Check 16: Monolithic Code Structure
        if "function" in user_message.lower() or "naming" in user_message.lower() or "modular" in user_message.lower():
            has_custom_funcs = False
            for match in re.finditer(r'\b(void|int|bool|float|double|String|char|long|unsigned(?:\s+long)?)\s+([a-zA-Z0-9_]+)\s*\(', code):
                if match.group(2) not in ['setup', 'loop', 'main']:
                    has_custom_funcs = True
                    break
            
            if not has_custom_funcs:
                issues.append({
                    "severity": "error",
                    "message": "Structure Violation: Request asked for functions but code is monolithic.",
                    "fix": lambda c: c.replace("void loop() {", "void loop() {\n  runSystemLogic();\n}\n\nvoid runSystemLogic() {") + "\n}"
                })

        # Check 17: Loop Length (Modularity)
        if "function" in user_message.lower() or "naming" in user_message.lower() or "modular" in user_message.lower():
            loop_match = re.search(r'void\s+loop\s*\(\s*\)\s*\{', code)
            if loop_match:
                start_idx = loop_match.end()
                brace_count = 1
                loop_body = ""
                
                for char in code[start_idx:]:
                    if char == '{': brace_count += 1
                    elif char == '}': brace_count -= 1
                    
                    if brace_count == 0:
                        break
                    loop_body += char
                
                # Count significant lines
                lines = [line.strip() for line in loop_body.split('\n')]
                significant_lines = [l for l in lines if l and not l.startswith('//') and not l.startswith('/*') and l != '']
                
                if len(significant_lines) >= 10:
                    issues.append({
                        "severity": "error",
                        "message": f"Modularity Violation: loop() has {len(significant_lines)} lines (limit 10). Move logic to functions.",
                        "fix": lambda c: self.refactor_loop_to_function(c)
                    })

        # Check 18: ADC Resolution (ESP32)
        if "ESP32" in hardware.upper():
            adc_res_match = re.search(r'#define\s+(\w*ADC\w*RES\w*)\s+(\d+)', code, re.IGNORECASE)
            if adc_res_match:
                val = int(adc_res_match.group(2))
                if val not in [4095, 4096]:
                     issues.append({
                        "severity": "error",
                        "line": self.find_line(code, adc_res_match.group(0)),
                        "message": f"Hardware Mismatch: ESP32 ADC is 12-bit (4095), not {val}.",
                        "fix": lambda c, old=adc_res_match.group(0), name=adc_res_match.group(1): c.replace(old, f"#define {name} 4095")
                    })
            
            # Check 20: Hardcoded 10-bit ADC math
            # Matches / 1023, / 1023.0, / 1024.0 (avoiding / 1024 int for bytes)
            for match in re.finditer(r'/\s*(1023(?:\.0?)?f?|1024(?:\.0)f?)', code):
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, match.group(0)),
                    "message": "Hardware Mismatch: ESP32 ADC is 12-bit. Use 4095.0, not 1023/1024.",
                    "fix": lambda c, m=match.group(0): c.replace(m, "/ 4095.0")
                })

        # Check 21: Status LED Pattern
        if "status" in user_message.lower() and ("led" in user_message.lower() or "indicator" in user_message.lower()):
            # Detect breathing logic (incrementing duty cycle in loop)
            breathing_match = re.search(r'(?:dutyCycle|brightness)\s*(\+=|\+\+|\-=|\-\-)', code)
            if breathing_match:
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, breathing_match.group(0)),
                    "message": "Wrong Pattern: Status indicators should use Blink Patterns (States), not Breathing/Fading.",
                    "fix": lambda c: c + "\n// [Fix Required] Implement setStatusLED(LEDStatus state) instead of fading."
                })

            # Check for missing Enum
            if not re.search(r'enum\s+(?:StatusState|LEDStatus)\s*\{', code):
                issues.append({
                    "severity": "error",
                    "message": "Missing Status Enum: Status LEDs require a state machine (enum LEDStatus {OFF, IDLE, ACTIVE, ERROR}).",
                    "fix": lambda c: c.replace("void setup", "\n// [AUTO-FIX] Status Enum\nenum LEDStatus { OFF, IDLE, ACTIVE, ERROR };\nLEDStatus currentStatus = IDLE;\nunsigned long lastBlink = 0;\n\nvoid setup") if "void setup" in c else "// [AUTO-FIX] Status Enum\nenum LEDStatus { OFF, IDLE, ACTIVE, ERROR };\nLEDStatus currentStatus = IDLE;\nunsigned long lastBlink = 0;\n" + c
                })

        # Check 19: Unnecessary Debouncing (Analog/Battery)
        if "battery" in user_message.lower() or "voltage" in user_message.lower() or "analog" in user_message.lower():
            if "button" not in user_message.lower():
                debounce_match = re.search(r'(?:debounce|lastDebounceTime)', code, re.IGNORECASE)
                if debounce_match:
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, debounce_match.group(0)),
                        "message": "Logic Error: Debouncing detected in analog/battery code. Analog sensors don't need debouncing.",
                        "fix": lambda c: re.sub(r'.*debounce.*', '// [Fixed] Removed unnecessary debounce logic', c, flags=re.IGNORECASE)
                    })

        # Check 12: Undefined Pin Constants
        pin_vars = set(re.findall(r'(?:digitalRead|digitalWrite|pinMode|ledcAttachPin)\s*\(\s*([a-zA-Z_]\w+)', code))
        for var in pin_vars:
            if var in ['LED_BUILTIN', 'HIGH', 'LOW', 'INPUT', 'OUTPUT', 'INPUT_PULLUP', 'true', 'false']:
                continue
            
            # Check if defined
            is_defined = re.search(r'#define\s+' + re.escape(var) + r'\b', code) or \
                         re.search(r'\b(?:const\s+)?(?:int|byte|uint8_t|short)\s+' + re.escape(var) + r'\s*=', code)
            
            if not is_defined:
                issues.append({
                    "severity": "error",
                    "message": f"Undefined variable '{var}' used in pin operation.",
                    "fix": lambda c, v=var: f"#define {v} 2 // [Auto-Fix] Defined missing pin\n" + c
                })
        
        # Check 22: Misused Debouncing (Animation Timing)
        if "brightness" in code or "fade" in code:
            misused_debounce = re.search(r'if\s*\(\s*\(?\s*millis\(\)\s*-\s*\w+\s*\)?\s*>\s*(\w*DEBOUNCE\w*)\s*\)\s*\{', code, re.IGNORECASE)
            if misused_debounce:
                var_name = misused_debounce.group(1)
                # Check if the block actually modifies brightness (simple heuristic lookahead)
                start_index = misused_debounce.end()
                snippet = code[start_index:start_index+200]
                if any(x in snippet for x in ['brightness', 'fade', 'dutyCycle', 'ledcWrite']):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, var_name),
                        "message": f"Semantic Error: Using {var_name} for animation/fading. Use UPDATE_INTERVAL or FADE_SPEED.",
                        "fix": lambda c, v=var_name: c.replace(v, "FADE_SPEED" if v.isupper() else "fadeSpeed")
                    })

        # Check 24: Unused Variables in Setup
        setup_match = re.search(r'void\s+setup\s*\(\s*\)\s*\{', code)
        if setup_match:
            start_idx = setup_match.end()
            brace_count = 1
            setup_body = ""
            for char in code[start_idx:]:
                if char == '{': brace_count += 1
                elif char == '}': brace_count -= 1
                if brace_count == 0: break
                setup_body += char
            
            clean_body = re.sub(r'//.*', '', setup_body)
            clean_body = re.sub(r'/\*.*?\*/', '', clean_body, flags=re.DOTALL)

            local_vars = re.finditer(r'\b((?:static\s+)?(?:const\s+)?(?:int|float|bool|char|String|long|double|byte|uint8_t|unsigned(?:\s+long)?))\s+([a-zA-Z_]\w*)\s*(?:=|;)', clean_body)
            
            for match in local_vars:
                var_type = match.group(1)
                var_name = match.group(2)
                if len(re.findall(r'\b' + re.escape(var_name) + r'\b', clean_body)) == 1:
                    issues.append({
                        "severity": "warning",
                        "line": self.find_line(code, f"{var_type} {var_name}"),
                        "message": f"Unused variable '{var_name}' in setup().",
                        "fix": lambda c, v=var_name, t=var_type: re.sub(r'\b' + re.escape(t) + r'\s+' + re.escape(v) + r'[^;]*;\s*', '', c)
                    })

        # Check 25: Missing Serial.begin
        if re.search(r'Serial\.(?:print|write|println|printf)', code) and not re.search(r'Serial\.begin\s*\(', code):
            issues.append({
                "severity": "error",
                "message": "Missing Serial.begin() initialization.",
                "fix": lambda c: re.sub(r'void\s+setup\s*\(\s*\)\s*\{', r'void setup() {\n  Serial.begin(115200);', c, count=1)
            })

        # Check 26: Missing Wire.begin
        if re.search(r'Wire\.(?!h\b|begin\b)', code) and not re.search(r'Wire\.begin\s*\(', code):
            issues.append({
                "severity": "error",
                "message": "Missing Wire.begin() initialization for I2C.",
                "fix": lambda c: re.sub(r'void\s+setup\s*\(\s*\)\s*\{', r'void setup() {\n  Wire.begin();', c, count=1)
            })

        return len([i for i in issues if i['severity'] == 'error']) == 0, issues
    
    def auto_fix(self, code: str, issues: List[Dict]) -> str:
        """Automatically fix known issues"""
        fixed_code = code
        
        for issue in issues:
            if 'fix' in issue and issue['severity'] == 'error':
                fixed_code = issue['fix'](fixed_code)
        
        return fixed_code


class AdaptiveLearner:
    """Learn from every interaction"""
    
    def learn_from_session(self, session_id: str):
        """Analyze what worked/failed in a session"""
        print(f"🧠 Adaptive Learning: Analyzing Session {session_id}...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get all messages in session
        cursor.execute("""
            SELECT id, role, content 
            FROM messages 
            WHERE session_id = ? 
            ORDER BY id ASC
        """, (session_id,))
        
        messages = cursor.fetchall()
        conn.close()
        
        count = 0
        # Look for correction patterns
        for i, (msg_id, role, content) in enumerate(messages):
            if role == 'user' and i > 0:
                prev_msg = messages[i-1]
                prev_role = prev_msg[1]
                prev_content = prev_msg[2]
                
                if prev_role == 'assistant':
                    # Did James correct the previous response?
                    if self.is_correction(content, prev_content):
                        print(f"  - Detected correction in msg #{msg_id}")
                        self.learn_correction(prev_content, content)
                        count += 1
                    
                    # Did James ask for modification?
                    if self.is_modification(content):
                        print(f"  - Detected preference in msg #{msg_id}")
                        self.learn_preference(content)
                        count += 1
        
        if count == 0:
            print("  - No obvious corrections found.")
    
    def is_correction(self, user_msg: str, ai_msg: str) -> bool:
        """Detect if user is correcting AI"""
        correction_signals = [
            "actually", "no,", "wrong", "should be", "instead of",
            "not", "use", "don't use", "change", "fix", "error", "bug"
        ]
        return any(signal in user_msg.lower() for signal in correction_signals)
    
    def is_modification(self, user_msg: str) -> bool:
        """Detect if user is expressing a preference"""
        signals = ["prefer", "i like", "always use", "style", "better", "make it"]
        return any(s in user_msg.lower() for s in signals)
    
    def learn_correction(self, original: str, correction: str):
        """Extract the lesson from a correction"""
        # Save the rule (Generic capture for now)
        rule_text = correction.split('\n')[0][:100]
        self.save_rule(rule_text, "context_dependent", correction[:100], confidence=0.5)
        
    def learn_preference(self, content: str):
        """Extract preference"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO style_preferences (user_id, category, preference, confidence, extracted_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("default", "learned_preference", content[:200], 0.6, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def save_rule(self, rule_text, find, replace, confidence):
        """Save to code_rules table"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO code_rules 
            (rule_text, pattern_find, pattern_replace, confidence, learned_from)
            VALUES (?, ?, ?, ?, ?)
        """, (rule_text, find, replace, confidence, 'adaptive_session'))
        conn.commit()
        conn.close()


class LearningMetrics:
    """Measure BuddAI's improvement over time"""
    
    def calculate_accuracy(self):
        """What % of code is accepted without correction?"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_responses,
                COUNT(CASE WHEN f.positive = 1 THEN 1 END) as positive_feedback,
                COUNT(CASE WHEN c.id IS NOT NULL THEN 1 END) as corrected
            FROM messages m
            LEFT JOIN feedback f ON m.id = f.message_id
            LEFT JOIN corrections c ON m.content LIKE '%' || c.original_code || '%'
            WHERE m.role = 'assistant'
            AND m.timestamp > ?
        """, (thirty_days_ago,))
        
        total, positive, corrected = cursor.fetchone()
        conn.close()
        
        accuracy = (positive / total) * 100 if total and total > 0 else 0
        correction_rate = (corrected / total) * 100 if total and total > 0 else 0
        
        return {
            "accuracy": accuracy,
            "correction_rate": correction_rate,
            "improvement": self.calculate_trend()
        }
    
    def calculate_trend(self):
        """Is BuddAI getting better over time?"""
        # Compare last 7 days vs previous 7 days
        recent = self.get_accuracy_for_period(7)
        previous = self.get_accuracy_for_period(7, offset=7)
        
        improvement = recent - previous
        return f"+{improvement:.1f}%" if improvement > 0 else f"{improvement:.1f}%"

    def get_accuracy_for_period(self, days: int, offset: int = 0) -> float:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        start_dt = (datetime.now() - timedelta(days=days + offset)).isoformat()
        end_dt = (datetime.now() - timedelta(days=offset)).isoformat()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN f.positive = 1 THEN 1 END) as positive
            FROM messages m
            LEFT JOIN feedback f ON m.id = f.message_id
            WHERE m.role = 'assistant'
            AND m.timestamp BETWEEN ? AND ?
        """, (start_dt, end_dt))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return 0.0
            
        total, positive = row
        return (positive / total) * 100 if total and total > 0 else 0.0


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
            if any(kw in message_lower for kw in keywords):
                module_count += 1
        
        # Complex if: multiple triggers OR 3+ modules mentioned
        return trigger_count >= 2 or module_count >= 3
        
    def extract_modules(self, message: str) -> List[str]:
        """Extract which modules are needed"""
        message_lower = message.lower()
        needed_modules = []
        
        for module, keywords in MODULE_PATTERNS.items():
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
            return self.call_model("fast", user_message)
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
            iterator = self.call_model("fast", user_message, stream=True)
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


# --- Server Implementation ---
if SERVER_AVAILABLE:
    app = FastAPI(title="BuddAI API", version="3.2")
    
    # Allow React frontend to communicate
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class ChatRequest(BaseModel):
        message: str
        model: Optional[str] = None
        forge_mode: Optional[str] = "2"

    class SessionLoadRequest(BaseModel):
        session_id: str

    class SessionRenameRequest(BaseModel):
        session_id: str
        title: str

    class SessionDeleteRequest(BaseModel):
        session_id: str

    class FeedbackRequest(BaseModel):
        message_id: int
        positive: bool
        comment: str = ""
        
    class ResetGpuRequest(BaseModel):
        pass

    # Multi-user support
    class BuddAIManager:
        def __init__(self):
            self.instances: Dict[str, BuddAI] = {}
        
        def get_instance(self, user_id: str) -> BuddAI:
            if user_id not in self.instances:
                self.instances[user_id] = BuddAI(user_id=user_id, server_mode=True)
            return self.instances[user_id]

    buddai_manager = BuddAIManager()

    # Serve Frontend
    frontend_path = Path(__file__).parent / "frontend"
    frontend_path.mkdir(exist_ok=True)
    app.mount("/web", StaticFiles(directory=frontend_path, html=True), name="web")

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        server_buddai = buddai_manager.get_instance("default")
        status = server_buddai.get_user_status()
        
        public_url = getattr(request.app.state, "public_url", "")
        qr_section = ""
        ip_section = ""
        
        if public_url:
            parsed = urlparse(public_url)
            host = parsed.hostname
            label = "Server Address"
            color = "#fff"
            
            if host:
                if host.startswith("100."):
                    label = "Tailscale IP"
                    color = "#ff79c6" # Magenta
                elif host.startswith("192.168.") or host.startswith("10.") or host.startswith("172."):
                    label = "LAN IP"
                    color = "#50fa7b" # Green
                elif "ngrok" in public_url:
                    label = "Public Tunnel"
                    color = "#8be9fd" # Cyan

                ip_section = f"""
                <div style="margin: 20px 0; text-align: center;">
                    <p style="margin: 0; font-size: 0.8em; color: #888; text-transform: uppercase; letter-spacing: 1px;">{label}</p>
                    <h2 style="margin: 5px 0; font-size: 1.8em; color: {color}; font-family: monospace; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);">{host}</h2>
                </div>
                """

            qr_section = f"""
            <div style="margin-top: 20px; text-align: center; background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px;">
                <p style="margin: 0 0 10px 0; font-size: 0.9em; color: #aaa;">Scan to Connect</p>
                <img src="/api/utils/qrcode?url={public_url}" style="width: 150px; height: 150px; border-radius: 8px; display: block; margin: 0 auto;">
            </div>
            """
        
        # System Stats
        mem_usage = "N/A"
        if psutil:
            process = psutil.Process(os.getpid())
            mem_usage = f"{process.memory_info().rss / 1024 / 1024:.0f} MB"
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sessions")
        total_sessions = cursor.fetchone()[0]
        conn.close()

        return f"""
        <html>
            <head>
                <title>BuddAI API (Dev Mode)</title>
                <link rel="icon" href="/favicon.ico">
                <style>
                    body {{ 
                        background: linear-gradient(135deg, #111 0%, #1a1a1a 100%); 
                        color: #e0e0e0; 
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                        display: flex; 
                        flex-direction: column; 
                        align-items: center; 
                        justify-content: center; 
                        height: 100vh; 
                        margin: 0; 
                    }}
                    .dashboard {{
                        display: flex;
                        gap: 15px;
                        margin: 20px 0;
                        width: 100%;
                        justify-content: center;
                    }}
                    .stat-card {{
                        background: rgba(255, 255, 255, 0.05);
                        padding: 15px;
                        border-radius: 10px;
                        min-width: 80px;
                        border: 1px solid rgba(255, 255, 255, 0.1);
                    }}
                    .stat-value {{
                        display: block;
                        font-size: 1.2em;
                        font-weight: bold;
                        color: #fff;
                    }}
                    .stat-label {{
                        font-size: 0.8em;
                        color: #888;
                    }}
                    .container {{
                        text-align: center;
                        background: rgba(255, 255, 255, 0.03);
                        padding: 40px;
                        border-radius: 16px;
                        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
                        backdrop-filter: blur(5px);
                        border: 1px solid rgba(255, 255, 255, 0.05);
                        max-width: 400px;
                        width: 90%;
                    }}
                    img {{ 
                        width: 120px; 
                        margin-bottom: 1.5rem; 
                        filter: drop-shadow(0 0 15px rgba(255, 152, 0, 0.3));
                        animation: float 6s ease-in-out infinite;
                    }}
                    h1 {{ margin: 0 0 10px 0; font-weight: 600; letter-spacing: 0.5px; color: #fff; }}
                    p {{ margin: 10px 0; color: #888; font-size: 0.95em; }}
                    strong {{ color: #ddd; }}
                    .links {{ margin-top: 30px; display: flex; gap: 15px; justify-content: center; }}
                    a {{ 
                        text-decoration: none; 
                        color: #fff; 
                        background: #0e639c; 
                        padding: 10px 20px; 
                        border-radius: 6px; 
                        transition: all 0.2s; 
                        font-weight: 600;
                        font-size: 0.9em;
                    }}
                    a:hover {{ background: #1177bb; transform: translateY(-2px); }}
                    a.secondary {{ background: transparent; border: 1px solid #444; color: #ccc; }}
                    a.secondary:hover {{ background: #333; border-color: #666; color: #fff; }}
                    
                    @keyframes float {{
                        0% {{ transform: translateY(0px); }}
                        50% {{ transform: translateY(-10px); }}
                        100% {{ transform: translateY(0px); }}
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <img src="/favicon.ico" alt="BuddAI">
                    <h1>BuddAI API</h1>
                    <p>Status: <span style="color: #4caf50; font-weight: bold;">● Online</span></p>
                    <p>Context: <strong>{status}</strong></p>
                    <div class="dashboard">
                        <div class="stat-card">
                            <span class="stat-value">{mem_usage}</span>
                            <span class="stat-label">Memory</span>
                        </div>
                        <div class="stat-card">
                            <span class="stat-value">{total_sessions}</span>
                            <span class="stat-label">Sessions</span>
                        </div>
                        <div class="stat-card">
                            <span class="stat-value">{len(buddai_manager.instances)}</span>
                            <span class="stat-label">Active Users</span>
                        </div>
                    </div>
                    <div class="links">
                        <a href="/web">Launch Web UI</a>
                        <a href="/docs" class="secondary">API Docs</a>
                    </div>
                    {ip_section}
                    {qr_section}
                </div>
            </body>
        </html>
        """

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(Path(__file__).parent / "icons" / "icon.png")

    @app.get("/favicon-16x16.png", include_in_schema=False)
    async def favicon_16():
        return FileResponse(Path(__file__).parent / "icons" / "favicon-16x16.png")

    @app.get("/favicon-32x32.png", include_in_schema=False)
    async def favicon_32():
        return FileResponse(Path(__file__).parent / "icons" / "favicon-32x32.png")

    @app.get("/favicon-192x192.png", include_in_schema=False)
    async def favicon_192():
        return FileResponse(Path(__file__).parent / "icons" / "favicon-192x192.png")

    def validate_upload(file: UploadFile) -> bool:
        # Check size
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        
        if size > MAX_FILE_SIZE:
            raise ValueError(f"File too large (Limit: {MAX_FILE_SIZE//1024//1024}MB)")
            
        # Magic number check for ZIPs
        if file.filename.lower().endswith('.zip'):
            header = file.file.read(4)
            file.file.seek(0)
            if header != b'PK\x03\x04':
                 raise ValueError("Invalid ZIP file header")

        if file.content_type not in ALLOWED_TYPES:
            # Fallback: check extension if content_type is generic
            ext = Path(file.filename).suffix.lower()
            if ext not in ['.zip', '.py', '.ino', '.cpp', '.h', '.js', '.jsx', '.html', '.css']:
                raise ValueError("Invalid file type")
        # Scan for malicious content
        return True

    def sanitize_filename(filename: str) -> str:
        clean = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        return clean if clean else "upload.bin"

    def safe_extract_zip(zip_path: Path, extract_path: Path):
        """Extract zip file with Zip Slip protection"""
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                target_path = extract_path / member.filename
                # Resolve paths to ensure they stay within extract_path
                if not str(target_path.resolve()).startswith(str(extract_path.resolve())):
                    raise ValueError(f"Malicious zip member: {member.filename}")
            zip_ref.extractall(extract_path)

    @app.post("/api/chat")
    async def chat_endpoint(request: ChatRequest, user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        response = server_buddai.chat(request.message, force_model=request.model, forge_mode=request.forge_mode)
        return {"response": response, "message_id": server_buddai.last_generated_id}

    @app.websocket("/api/ws/chat")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_json()
                user_message = data.get("message")
                user_id = data.get("user_id", "default")
                model = data.get("model")
                forge_mode = data.get("forge_mode", "2")
                
                server_buddai = buddai_manager.get_instance(user_id)
                
                for chunk in server_buddai.chat_stream(user_message, model, forge_mode):
                    await websocket.send_json({"type": "token", "content": chunk})
                    
                await websocket.send_json({"type": "end", "message_id": server_buddai.last_generated_id})
        except WebSocketDisconnect:
            pass

    @app.post("/api/feedback")
    async def feedback_endpoint(req: FeedbackRequest, user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        new_response = server_buddai.record_feedback(req.message_id, req.positive, req.comment)
        if new_response:
            return {"status": "regenerated", "response": new_response, "message_id": server_buddai.last_generated_id}
        return {"status": "success"}

    @app.post("/api/system/reset-gpu")
    async def reset_gpu_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        result = server_buddai.reset_gpu()
        return {"message": result}

    @app.get("/api/system/metrics")
    async def metrics_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        return server_buddai.metrics.calculate_accuracy()

    @app.get("/api/system/status")
    async def system_status_endpoint():
        mem_percent = 0
        cpu_percent = 0
        if psutil:
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            cpu_percent = psutil.cpu_percent(interval=None)
        return {"memory": mem_percent, "cpu": cpu_percent}

    @app.get("/api/system/backup")
    async def backup_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        success, path_or_err = server_buddai.create_backup()
        
        if success:
            return FileResponse(
                path=path_or_err, 
                filename=Path(path_or_err).name,
                media_type='application/x-sqlite3'
            )
        else:
            return JSONResponse(status_code=500, content={"message": f"Backup failed: {path_or_err}"})

    @app.get("/api/utils/qrcode")
    async def qrcode_endpoint(url: str):
        if not qrcode:
            return JSONResponse(status_code=501, content={"message": "qrcode module missing"})
        
        try:
            img = qrcode.make(url)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(content=buf.getvalue(), media_type="image/png")
        except Exception as e:
            return JSONResponse(status_code=500, content={"message": f"QR Error: {str(e)}. Ensure 'pillow' is installed."})

    @app.get("/api/history")
    async def history_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        return {"history": server_buddai.context_messages}

    @app.get("/api/sessions")
    async def sessions_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        return {"sessions": server_buddai.get_sessions()}

    @app.post("/api/session/load")
    async def load_session_endpoint(req: SessionLoadRequest, user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        history = server_buddai.load_session(req.session_id)
        return {"history": history, "session_id": req.session_id}

    @app.post("/api/session/rename")
    async def rename_session_endpoint(req: SessionRenameRequest, user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        server_buddai.rename_session(req.session_id, req.title)
        return {"status": "success"}

    @app.post("/api/session/delete")
    async def delete_session_endpoint(req: SessionDeleteRequest, user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        server_buddai.delete_session(req.session_id)
        return {"status": "success"}

    @app.get("/api/session/{session_id}/export/json")
    async def export_json_endpoint(session_id: str, user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        data = server_buddai.get_session_export_data(session_id)
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f"attachment; filename=session_{session_id}.json"}
        )

    @app.post("/api/session/import")
    async def import_session_endpoint(file: UploadFile = File(...), user_id: str = Header("default")):
        if not file.filename.lower().endswith('.json'):
             return JSONResponse(status_code=400, content={"message": "Invalid file type. Must be JSON."})
             
        content = await file.read()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"message": "Invalid JSON content."})
            
        server_buddai = buddai_manager.get_instance(user_id)
        try:
            new_session_id = server_buddai.import_session_from_json(data)
            return {"status": "success", "session_id": new_session_id, "message": f"Session imported as {new_session_id}"}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"message": str(e)})
        except Exception as e:
            return JSONResponse(status_code=500, content={"message": f"Server error: {str(e)}"})

    @app.post("/api/session/clear")
    async def clear_session_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        server_buddai.clear_current_session()
        return {"status": "success"}

    @app.post("/api/session/new")
    async def new_session_endpoint(user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        new_id = server_buddai.start_new_session()
        return {"session_id": new_id}

    @app.post("/api/upload")
    async def upload_repo(file: UploadFile = File(...), user_id: str = Header("default")):
        server_buddai = buddai_manager.get_instance(user_id)
        try:
            validate_upload(file)
            
            uploads_dir = DATA_DIR / "uploads"
            uploads_dir.mkdir(exist_ok=True)
            
            # Enforce MAX_UPLOAD_FILES (Hardening)
            existing_items = sorted(uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime)
            while len(existing_items) >= MAX_UPLOAD_FILES:
                oldest = existing_items.pop(0)
                if oldest.is_dir():
                    shutil.rmtree(oldest)
                else:
                    oldest.unlink()
            
            safe_name = sanitize_filename(file.filename)
            file_location = uploads_dir / safe_name
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            if safe_name.lower().endswith(".zip"):
                extract_path = uploads_dir / file_location.stem
                extract_path.mkdir(exist_ok=True)
                safe_extract_zip(file_location, extract_path)
                server_buddai.index_local_repositories(extract_path)
                file_location.unlink() # Cleanup zip
                return {"message": f"✅ Successfully indexed {safe_name}"}
            else:
                # Support single code files by moving them to a folder and indexing
                if file_location.suffix.lower() in ['.py', '.ino', '.cpp', '.h', '.js', '.jsx', '.html', '.css']:
                    target_dir = uploads_dir / file_location.stem
                    target_dir.mkdir(exist_ok=True)
                    final_path = target_dir / safe_name
                    shutil.move(str(file_location), str(final_path))
                    server_buddai.index_local_repositories(target_dir)
                    return {"message": f"✅ Successfully indexed {safe_name}"}
                
                return {"message": f"✅ Successfully uploaded {safe_name}"}
        except Exception as e:
            return {"message": f"❌ Error: {str(e)}"}

def check_ollama() -> bool:
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=5)
        conn.request("GET", "/api/tags")
        response = conn.getresponse()
        if response.status == 200:
            data = json.loads(response.read().decode('utf-8'))
            conn.close()
            installed_models = [m['name'] for m in data.get('models', [])]
            missing = [m for m in MODELS.values() if m not in installed_models]
            if missing:
                print(f"⚠️  WARNING: Missing models in Ollama: {', '.join(missing)}")
                print(f"   Run in host terminal: ollama pull {' && ollama pull '.join(missing)}")
            return True
        return False
    except Exception:
        return False

def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except socket.error:
            return False

def main() -> None:
    if not check_ollama():
        print(f"❌ Ollama not running at {OLLAMA_HOST}:{OLLAMA_PORT}. Ensure it is running and accessible.")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description="BuddAI Executive")
    parser.add_argument("--server", action="store_true", help="Run in server mode")
    parser.add_argument("--port", type=int, default=8000, help="Port for server mode")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host IP address")
    parser.add_argument("--public-url", type=str, default="", help="Public URL for QR codes")
    args = parser.parse_args()

    if args.server:
        if SERVER_AVAILABLE:
            port = args.port
            if not is_port_available(port, args.host):
                print(f"⚠️ Port {port} is in use.")
                for i in range(1, 11):
                    if is_port_available(port + i, args.host):
                        port += i
                        print(f"🔄 Switching to available port: {port}")
                        break
                else:
                    print(f"❌ Could not find available port in range {args.port}-{args.port+10}")
                    sys.exit(1)
            
            # Silence health check logs from frontend polling
            class EndpointFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    msg = record.getMessage()
                    return "/api/system/status" not in msg and '"GET / HTTP/1.1" 200' not in msg
            logging.getLogger("uvicorn.access").addFilter(EndpointFilter())
            
            print(f"🚀 Starting BuddAI API Server on port {port}...")
            if args.public_url:
                print(f"🔗 Public Access: {args.public_url}")
                app.state.public_url = args.public_url
                
            uvicorn.run(app, host=args.host, port=port)
        else:
            print("❌ Server dependencies missing. Install: pip install fastapi uvicorn aiofiles python-multipart")
    else:
        buddai = BuddAI()
        buddai.run()


if __name__ == "__main__":
    main()