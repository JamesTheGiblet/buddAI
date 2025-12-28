# BuddAI Quick Start Guide

## You Are Here: Milestone 1 Complete! 🎉

You've successfully:

- ✅ Installed Ollama
- ✅ Downloaded DeepSeek model
- ✅ Had first conversation with base model

## Next: Add Persistent Memory

### Step 1: Set Up Files

1. **Copy these files to your BuddAI folder:**
   - `buddai.py` (the main script)
   - `requirements.txt` (dependencies - currently none needed!)
   - `README.md` (the manifesto you already have)

2. **Create data directory:**

   ```powershell
   mkdir data
   ```

   *(Note: If you see an error saying the item already exists, you can safely ignore it and proceed.)*

### Step 2: Run BuddAI with Memory

Instead of running raw Ollama, now run:

```powershell
python buddai.py
```

**What happens:**

- BuddAI starts with persistent memory enabled
- Conversation history saves to SQLite database
- Context from previous messages is maintained
- Session statistics are tracked

### Step 3: Test Memory

**First conversation:**

```
James: My name is James Gilbert. I'm building GilBots - modular combat robots.

BuddAI: [Acknowledges and responds]

James: exit
```

**Second conversation (later or tomorrow):**

```powershell
python buddai.py
```

```
James: What am I building?

BuddAI: [Should reference GilBots from previous session!]
```

**That's persistent memory working!**

---

## Available Commands

While in BuddAI:

- `/help` - Show all commands
- `/stats` - View session statistics
- `/history` - See recent conversation
- `/clear` - Start fresh (clear context)
- `/export` - Save session to JSON
- `exit` or `quit` - End session

---

## What You Can Do Now

### Test Code Generation

```
James: Generate ESP32 code for controlling two DC motors via L298N driver with PWM speed control
```

### Test Memory

```
James: Remember: I prefer modular code with clear comments. Keep functions under 50 lines.
```

Later:

```
James: Write a function to control a servo
```

It should remember your style preference!

### Test Context

```
James: I'm building a flipper mechanism for GilBot #1

James: What servo should I use?

James: How much torque do I need?
```

BuddAI maintains context across the conversation.

---

## Troubleshooting

### "Ollama not found"

Make sure Ollama is in your PATH. Test with:

```powershell
ollama list
```

### "Model not found"

The script will try to download it automatically. Or manually:

```powershell
ollama pull deepseek-coder:1.3b
```

### "Python not found"

Install Python 3.8+ from python.org

### Database errors

Delete `data/conversations.db` and restart - it will recreate.

---

## What's Next

**You're on Milestone 2 now: BuddAI Knows Your Work**

Next steps:

1. Test memory is working (sessions persist)
2. Have real conversations about your projects
3. Let BuddAI learn your preferences
4. Start building GilBot with BuddAI's help

**Then:** Add repository indexing (access to your 115 repos)

---

## Current Limitations

**What works:**

- ✅ Persistent memory across sessions
- ✅ Conversation context maintenance
- ✅ Code generation
- ✅ Session management

**What doesn't work yet:**

- ❌ Access to your GitHub repos (Milestone 2)
- ❌ Pattern learning from your code (Milestone 3)
- ❌ Proactive suggestions (Milestone 4)
- ❌ Voice interface (Milestone 6)

**But the foundation is SOLID.**

---

## File Structure

```
buddAI/
├── buddai.py           # Main script (run this)
├── README.md           # Full documentation
├── requirements.txt    # Dependencies (none yet!)
├── QUICKSTART.md       # This file
└── data/
    ├── conversations.db    # Auto-created
    └── session_*.json      # Exported sessions
```

---

## First Real Task

**Try building something with BuddAI right now:**

```
James: I need a Python script that calculates the center of gravity for a robot chassis. 
Inputs: component weights and positions (x, y, z).
Output: CG coordinates.
Keep it modular and well-commented.
```

Let BuddAI generate it. Debug it. **Feel the symbiosis starting.**

---

**Welcome to BuddAI v0.2 - Now with persistent memory!**

The exocortex is awakening. 🧠✨
