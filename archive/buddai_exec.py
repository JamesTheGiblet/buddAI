#!/usr/bin/env python3
"""
BuddAI Executive - Self-Learning Router
Simple weighted decision-making with feedback loop

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
import random

# Configuration
OLLAMA_HOST = "localhost"
OLLAMA_PORT = 11434
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "conversations.db"

# Available models
MODELS = {
    "fast": "qwen2.5-coder:1.5b",      # 5-10s
    "balanced": "qwen2.5-coder:3b",    # 15-30s (NEW - better for your slow laptop)
    "quality": "deepseek-coder:6.7b"   # 60-180s
}

# Decision weights (start balanced, will learn over time)
WEIGHTS = {
    # Fast triggers (simple questions, chat)
    "what": {"fast": 10, "balanced": 0, "quality": 0},
    "who": {"fast": 10, "balanced": 0, "quality": 0},
    "hello": {"fast": 10, "balanced": 0, "quality": 0},
    "hi": {"fast": 10, "balanced": 0, "quality": 0},
    "name": {"fast": 10, "balanced": 0, "quality": 0},
    "remember": {"fast": 8, "balanced": 2, "quality": 0},
    
    # Balanced triggers (medium complexity)
    "generate": {"fast": 2, "balanced": 8, "quality": 2},
    "create": {"fast": 2, "balanced": 8, "quality": 2},
    "write": {"fast": 2, "balanced": 8, "quality": 2},
    "code": {"fast": 1, "balanced": 8, "quality": 3},
    "function": {"fast": 2, "balanced": 8, "quality": 2},
    
    # Quality triggers (complex tasks - use sparingly on slow laptop)
    "complete": {"fast": 0, "balanced": 5, "quality": 10},
    "complex": {"fast": 0, "balanced": 3, "quality": 10},
    "debug": {"fast": 0, "balanced": 5, "quality": 8},
    "fix": {"fast": 1, "balanced": 7, "quality": 5},
    "build": {"fast": 0, "balanced": 6, "quality": 8},
    "entire": {"fast": 0, "balanced": 4, "quality": 10},
    
    # Length triggers
    "simple": {"fast": 9, "balanced": 2, "quality": 0},
    "quick": {"fast": 10, "balanced": 1, "quality": 0},
}

# Feedback counter (ask every N responses)
FEEDBACK_FREQUENCY = 5


class BuddAI:
    """Executive router with learning"""
    
    def __init__(self):
        self.ensure_data_dir()
        self.init_database()
        self.load_weights()
        self.session_id = self.create_session()
        self.context_messages = self.load_all_history(10)
        self.response_count = 0
        
        print("🧠 BuddAI Executive - Learning Router")
        print("=" * 50)
        print(f"Session: {self.session_id}")
        print(f"FAST (5-10s) | BALANCED (15-30s) | QUALITY (60-180s)")
        print(f"Loaded: {len(self.context_messages)} past messages")
        print("=" * 50)
        print("\nCommands: /fast, /balanced, /quality, /weights, exit\n")
        
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
                model_used TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Migration: Add model_used column if it doesn't exist
        try:
            cursor.execute("SELECT model_used FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            print("📦 Migrating database: adding model_used column...")
            cursor.execute("ALTER TABLE messages ADD COLUMN model_used TEXT")
            print("✅ Migration complete\n")
        
        # Learning table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routing_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                chosen_model TEXT,
                feedback TEXT,
                timestamp TIMESTAMP
            )
        """)
        
        # Weights table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weights (
                keyword TEXT PRIMARY KEY,
                fast_weight INTEGER,
                quality_weight INTEGER
            )
        """)
        
        conn.commit()
        conn.close()
        
    def load_weights(self):
        """Load learned weights from database or use defaults"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT keyword, fast_weight, quality_weight FROM weights")
        rows = cursor.fetchall()
        conn.close()
        
        # Update weights with learned values
        for keyword, fast_w, quality_w in rows:
            if keyword in WEIGHTS:
                WEIGHTS[keyword] = {"fast": fast_w, "quality": quality_w}
                
    def save_weights(self):
        """Save current weights to database"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for keyword, weights in WEIGHTS.items():
            cursor.execute(
                "INSERT OR REPLACE INTO weights (keyword, fast_weight, quality_weight) VALUES (?, ?, ?)",
                (keyword, weights["fast"], weights["quality"])
            )
        conn.commit()
        conn.close()
        
    def decide_model(self, user_message):
        """Simple weighted decision based on keywords - now with 3 tiers"""
        message_lower = user_message.lower()
        
        fast_score = 0
        balanced_score = 0
        quality_score = 0
        matched_keywords = []
        
        # Check each keyword
        for keyword, weights in WEIGHTS.items():
            if keyword in message_lower:
                fast_score += weights.get("fast", 0)
                balanced_score += weights.get("balanced", 0)
                quality_score += weights.get("quality", 0)
                matched_keywords.append(keyword)
        
        # Default to fast if no keywords matched
        if fast_score == 0 and balanced_score == 0 and quality_score == 0:
            return "fast", matched_keywords, 5  # low confidence
        
        # Choose model based on highest score
        total = fast_score + balanced_score + quality_score
        scores = {
            "fast": fast_score,
            "balanced": balanced_score,
            "quality": quality_score
        }
        
        chosen = max(scores, key=scores.get)
        confidence = int((scores[chosen] / total) * 100) if total > 0 else 50
            
        return chosen, matched_keywords, confidence
        
    def adjust_weights(self, keywords, chosen_model, feedback):
        """Adjust weights based on feedback"""
        if not keywords:
            return
            
        adjustment = 2  # How much to adjust
        
        if feedback == "good":
            # Reinforce this decision
            for kw in keywords:
                if kw in WEIGHTS:
                    WEIGHTS[kw][chosen_model] += adjustment
        elif feedback == "faster":
            # Should have used fast
            for kw in keywords:
                if kw in WEIGHTS:
                    WEIGHTS[kw]["fast"] += adjustment
                    WEIGHTS[kw]["quality"] -= adjustment
        elif feedback == "better":
            # Should have used quality
            for kw in keywords:
                if kw in WEIGHTS:
                    WEIGHTS[kw]["quality"] += adjustment
                    WEIGHTS[kw]["fast"] -= adjustment
                    
        # Keep weights positive
        for kw in WEIGHTS:
            WEIGHTS[kw]["fast"] = max(0, WEIGHTS[kw]["fast"])
            WEIGHTS[kw]["quality"] = max(0, WEIGHTS[kw]["quality"])
            
        self.save_weights()
        
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
        
    def save_message(self, role, content, model=None):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, model_used, timestamp) VALUES (?, ?, ?, ?, ?)",
            (self.session_id, role, content, model, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        
    def save_feedback(self, query, model, feedback):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO routing_feedback (query, chosen_model, feedback, timestamp) VALUES (?, ?, ?, ?)",
            (query, model, feedback, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        
    def load_all_history(self, limit=10):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM messages ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        messages = cursor.fetchall()
        conn.close()
        return [{"role": role, "content": content} for role, content in reversed(messages)]
        
    def call_model(self, model_name, user_message):
        """Call specific model"""
        try:
            # Build context
            messages = []
            for msg in self.context_messages[-5:]:
                messages.append(msg)
            
            # Add identity and current message
            identity = "[You are BuddAI. Help James build GilBots. Be direct and helpful.]\n\n"
            messages.append({"role": "user", "content": identity + user_message})
            
            body = {
                "model": MODELS[model_name],
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_ctx": 2048}
            }
            
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=180)  # 3 minutes for quality
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
                
    def chat(self, user_message, force_model=None):
        """Main chat with routing"""
        # Decide which model to use
        if force_model:
            chosen_model = force_model
            keywords = []
            confidence = 100
        else:
            chosen_model, keywords, confidence = self.decide_model(user_message)
        
        # Show decision
        print(f"\n🎯 Using: {chosen_model.upper()} model", end="")
        if keywords:
            print(f" (matched: {', '.join(keywords[:3])})", end="")
        print(f" - confidence: {confidence}%")
        print("⚡ Thinking...\n")
        
        # Save user message
        self.save_message("user", user_message)
        self.context_messages.append({"role": "user", "content": user_message})
        
        # Call model
        response = self.call_model(chosen_model, user_message)
        
        # Save response
        self.save_message("assistant", response, chosen_model)
        self.context_messages.append({"role": "assistant", "content": response})
        
        # Track for feedback
        self.last_query = user_message
        self.last_model = chosen_model
        self.last_keywords = keywords
        self.response_count += 1
        
        return response
        
    def ask_feedback(self):
        """Occasionally ask for feedback"""
        print("\n" + "=" * 50)
        print(f"Was {self.last_model.upper()} the right choice?")
        print("  good    - Perfect!")
        print("  faster  - Too slow, use FAST next time")
        print("  better  - Too basic, use QUALITY next time")
        print("  skip    - Don't adjust")
        feedback = input("Feedback: ").strip().lower()
        print("=" * 50)
        
        if feedback in ["good", "faster", "better"]:
            self.adjust_weights(self.last_keywords, self.last_model, feedback)
            self.save_feedback(self.last_query, self.last_model, feedback)
            print(f"✅ Learned! Weights updated.\n")
        else:
            print("⏭️  Skipped\n")
            
    def show_weights(self):
        """Show current weights"""
        print("\n📊 Current Routing Weights")
        print("=" * 50)
        for keyword, weights in sorted(WEIGHTS.items()):
            total = weights["fast"] + weights["quality"]
            if total > 0:
                fast_pct = int((weights["fast"] / total) * 100)
                quality_pct = 100 - fast_pct
                bar = "█" * (fast_pct // 5) + "░" * (quality_pct // 5)
                print(f"{keyword:12} [{bar}] F:{weights['fast']} Q:{weights['quality']}")
        print("=" * 50 + "\n")
        
    def run(self):
        """Main loop"""
        try:
            force_model = None
            
            while True:
                user_input = input("James: ").strip()
                
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
                        print("⚡ Next response: FAST model\n")
                        continue
                    elif cmd == '/balanced':
                        force_model = "balanced"
                        print("⚖️  Next response: BALANCED model\n")
                        continue
                    elif cmd == '/quality':
                        force_model = "quality"
                        print("🎯 Next response: QUALITY model\n")
                        continue
                    elif cmd == '/weights':
                        self.show_weights()
                        continue
                    else:
                        print("\nCommands: /fast, /balanced, /quality, /weights\n")
                        continue
                
                # Chat
                response = self.chat(user_input, force_model)
                print(f"BuddAI: {response}\n")
                
                # Reset force
                force_model = None
                
                # Ask for feedback occasionally
                if self.response_count % FEEDBACK_FREQUENCY == 0:
                    self.ask_feedback()
                    
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
        print("❌ Ollama not running. Start: ollama serve")
        sys.exit(1)
        
    buddai = BuddAI()
    buddai.run()


if __name__ == "__main__":
    main()