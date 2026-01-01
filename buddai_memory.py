#!/usr/bin/env python3
import sys, os, json, logging, sqlite3, datetime, pathlib, http.client, re, typing, zipfile, shutil, queue, socket, argparse, io, difflib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Union, Generator

from buddai_shared import DB_PATH, MODULE_PATTERNS

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
