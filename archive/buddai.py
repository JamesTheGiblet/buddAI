#!/usr/bin/env python3
"""
BuddAI - IP AI Exocortex
Core wrapper script providing persistent memory and conversation management

This script wraps Ollama's DeepSeek model with:
- Persistent conversation history (SQLite)
- Context injection (remembers past conversations)
- Session management
- Foundation for knowledge base integration

Author: James Gilbert (JamesTheGiblet)
License: MIT
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import subprocess

# Configuration
OLLAMA_MODEL = "deepseek-coder:1.3b"
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "conversations.db"
MAX_CONTEXT_MESSAGES = 20  # How many previous messages to include as context

# System prompt that defines BuddAI's identity
SYSTEM_PROMPT = """You are BuddAI, an IP AI Exocortex for James Gilbert (JamesTheGiblet on GitHub).

Your purpose is to extend James's cognitive capabilities by:
- Generating code in his modular, clean style
- Remembering all conversations and context
- Suggesting approaches based on his 115+ repositories of experience
- Helping him build things faster through symbiotic collaboration

James's background:
- Polymath creator working across robotics, 3D printing, coffee science, cannabis cultivation, LEGO conversions, and more
- Developer of Forge Theory: mathematical framework based on exponential decay, validated across multiple domains
- Works in 20-hour creative cycles, rapid prototyping approach
- Prefers modular design, clean code, simplicity over complexity
- Expert debugger but prefers AI assistance for code generation
- 115+ repositories spanning 8+ years of cross-domain work

Key projects to reference:
- CoffeeForge: Coffee roasting optimization using thermal modeling
- CannaForge: Cannabis cultivation science and optimization
- BlockForge: LEGO to 3D printable conversion suite
- GilBots: Modular combat robot designs (current project)
- EMBER: Autonomous phototropic robot
- Forge Theory: Exponential decay applications across domains

Your role:
- Generate code that matches James's style (modular, clean, well-commented)
- Remember context from previous conversations
- Suggest solutions based on his past work
- Be direct and practical, no unnecessary verbosity
- Learn from his corrections and preferences

You are not just an assistant - you are an extension of James's mind.
Work WITH him, not FOR him. This is symbiosis.
"""


class BuddAI:
    """Main BuddAI class managing conversation, memory, and Ollama interaction"""
    
    def __init__(self):
        """Initialize BuddAI with database connection and session"""
        self.ensure_data_dir()
        self.init_database()
        self.session_id = self.create_session()
        self.context_messages = []
        print("🤖 BuddAI - IP AI Exocortex")
        print("=" * 50)
        print(f"Session ID: {self.session_id}")
        print(f"Model: {OLLAMA_MODEL}")
        print(f"Database: {DB_PATH}")
        print("=" * 50)
        print("\nType 'exit' or 'quit' to end session")
        print("Type '/help' for commands\n")
        
    def ensure_data_dir(self):
        """Create data directory if it doesn't exist"""
        DATA_DIR.mkdir(exist_ok=True)
        
    def init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                message_count INTEGER DEFAULT 0
            )
        """)
        
        # Messages table
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
        
        # User preferences table (for future learning)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        
    def create_session(self):
        """Create a new conversation session"""
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
        """Mark session as ended"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET ended_at = ?, message_count = ? WHERE session_id = ?",
            (datetime.now().isoformat(), len(self.context_messages), self.session_id)
        )
        conn.commit()
        conn.close()
        
    def save_message(self, role, content):
        """Save a message to the database"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (self.session_id, role, content, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        
    def load_recent_context(self, limit=MAX_CONTEXT_MESSAGES):
        """Load recent conversation history for context"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content FROM messages 
            WHERE session_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
            """,
            (self.session_id, limit)
        )
        messages = cursor.fetchall()
        conn.close()
        
        # Reverse to get chronological order
        return [{"role": role, "content": content} for role, content in reversed(messages)]
        
    def build_prompt(self, user_message):
        """Build the complete prompt with system context and conversation history"""
        prompt_parts = [SYSTEM_PROMPT, "\n---\n"]
        
        # Add conversation history
        if self.context_messages:
            prompt_parts.append("Previous conversation:\n")
            for msg in self.context_messages[-MAX_CONTEXT_MESSAGES:]:
                role = "James" if msg["role"] == "user" else "BuddAI"
                prompt_parts.append(f"{role}: {msg['content']}\n")
            prompt_parts.append("\n---\n")
        
        # Add current message
        prompt_parts.append(f"James: {user_message}\n")
        prompt_parts.append("BuddAI: ")
        
        return "".join(prompt_parts)
        
    def call_ollama(self, prompt):
        """Call Ollama with the constructed prompt"""
        try:
            # Use subprocess to call Ollama with proper encoding handling
            result = subprocess.run(
                ["ollama", "run", OLLAMA_MODEL],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",  # Replace problematic characters instead of failing
                timeout=120  # 2 minute timeout
            )
            
            if result.returncode == 0:
                # Clean up any replacement characters and extra whitespace
                output = result.stdout.strip()
                # Remove common Unicode replacement artifacts
                output = output.replace('\ufffd', '')  # Unicode replacement character
                return output
            else:
                stderr = result.stderr if result.stderr else "Unknown error"
                return f"Error calling Ollama: {stderr}"
                
        except subprocess.TimeoutExpired:
            return "Error: Ollama request timed out (>2 minutes)"
        except FileNotFoundError:
            return "Error: Ollama not found. Is it installed and in PATH?"
        except UnicodeDecodeError as e:
            return f"Error: Unicode decoding failed - {str(e)}"
        except Exception as e:
            return f"Error: {str(e)}"
            
    def chat(self, user_message):
        """Main chat function - handles user input and generates response"""
        # Save user message
        self.save_message("user", user_message)
        self.context_messages.append({"role": "user", "content": user_message})
        
        # Build prompt with context
        full_prompt = self.build_prompt(user_message)
        
        # Get response from Ollama
        print("\n🤔 Thinking...\n")
        response = self.call_ollama(full_prompt)
        
        # Save assistant response
        self.save_message("assistant", response)
        self.context_messages.append({"role": "assistant", "content": response})
        
        return response
        
    def show_stats(self):
        """Show session statistics"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Total messages in current session
        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (self.session_id,)
        )
        session_count = cursor.fetchone()[0]
        
        # Total messages all time
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_count = cursor.fetchone()[0]
        
        # Total sessions
        cursor.execute("SELECT COUNT(*) FROM sessions")
        total_sessions = cursor.fetchone()[0]
        
        conn.close()
        
        print("\n📊 BuddAI Statistics")
        print("=" * 50)
        print(f"Current session: {session_count} messages")
        print(f"Total messages: {total_count}")
        print(f"Total sessions: {total_sessions}")
        print("=" * 50 + "\n")
        
    def show_history(self, limit=10):
        """Show recent conversation history"""
        messages = self.load_recent_context(limit)
        print("\n📜 Recent Conversation History")
        print("=" * 50)
        for msg in messages:
            role = "James" if msg["role"] == "user" else "BuddAI"
            content_preview = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            print(f"{role}: {content_preview}\n")
        print("=" * 50 + "\n")
        
    def show_help(self):
        """Show available commands"""
        print("\n💡 BuddAI Commands")
        print("=" * 50)
        print("/help       - Show this help message")
        print("/stats      - Show session statistics")
        print("/history    - Show recent conversation history")
        print("/clear      - Clear current session context (start fresh)")
        print("/export     - Export current session to JSON")
        print("exit/quit   - End session and exit")
        print("=" * 50 + "\n")
        
    def clear_context(self):
        """Clear current session context (keep in DB, just reset context)"""
        self.context_messages = []
        print("\n🧹 Context cleared. Starting fresh conversation.\n")
        
    def export_session(self):
        """Export current session to JSON file"""
        export_file = DATA_DIR / f"session_{self.session_id}.json"
        
        session_data = {
            "session_id": self.session_id,
            "messages": self.context_messages,
            "exported_at": datetime.now().isoformat()
        }
        
        with open(export_file, 'w') as f:
            json.dump(session_data, f, indent=2)
            
        print(f"\n💾 Session exported to: {export_file}\n")
        
    def run(self):
        """Main conversation loop"""
        try:
            while True:
                # Get user input
                user_input = input("James: ").strip()
                
                # Handle empty input
                if not user_input:
                    continue
                    
                # Handle exit commands
                if user_input.lower() in ['exit', 'quit', 'bye']:
                    print("\n👋 Ending session...")
                    self.end_session()
                    print("Session saved. See you next time, James!\n")
                    break
                    
                # Handle slash commands
                if user_input.startswith('/'):
                    command = user_input.lower()
                    if command == '/help':
                        self.show_help()
                    elif command == '/stats':
                        self.show_stats()
                    elif command == '/history':
                        self.show_history()
                    elif command == '/clear':
                        self.clear_context()
                    elif command == '/export':
                        self.export_session()
                    else:
                        print(f"\nUnknown command: {user_input}")
                        print("Type /help for available commands\n")
                    continue
                    
                # Process as normal chat message
                response = self.chat(user_input)
                print(f"\nBuddAI: {response}\n")
                
        except KeyboardInterrupt:
            print("\n\n👋 Session interrupted. Saving...")
            self.end_session()
            print("Goodbye, James!\n")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            self.end_session()
            raise


def main():
    """Main entry point"""
    # Check if Ollama is installed
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            print("❌ Error: Ollama is not responding properly.")
            print("Please ensure Ollama is installed and running.")
            sys.exit(1)
    except FileNotFoundError:
        print("❌ Error: Ollama not found.")
        print("Please install Ollama from: https://ollama.com/download")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error checking Ollama: {e}")
        sys.exit(1)
        
    # Check if model is available
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5
        )
        if OLLAMA_MODEL not in result.stdout:
            print(f"⚠️  Warning: Model {OLLAMA_MODEL} not found.")
            print(f"Attempting to pull model...")
            subprocess.run(["ollama", "pull", OLLAMA_MODEL])
    except Exception as e:
        print(f"⚠️  Warning: Could not verify model: {e}")
        
    # Start BuddAI
    buddai = BuddAI()
    buddai.run()


if __name__ == "__main__":
    main()