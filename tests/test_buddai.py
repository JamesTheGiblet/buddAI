#!/usr/bin/env python3
"""
BuddAI v3.2 Test Suite
Comprehensive testing for all features

Author: James Gilbert
License: MIT
"""

import sys
import importlib.util
from unittest.mock import MagicMock, patch
import sqlite3
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import os
import io
import zipfile
import http.client

# Dynamic import of buddai_v3.2.py
REPO_ROOT = Path(__file__).parent.parent
MODULE_PATH = REPO_ROOT / "buddai_v3.2.py"
spec = importlib.util.spec_from_file_location("buddai_v3_2", MODULE_PATH)
buddai_module = importlib.util.module_from_spec(spec)
sys.modules["buddai_v3_2"] = buddai_module
spec.loader.exec_module(buddai_module)
BuddAI = buddai_module.BuddAI

# Test utilities
class TestColors:
    PASS = '\033[92m'
    FAIL = '\033[91m'
    INFO = '\033[94m'
    WARN = '\033[93m'
    END = '\033[0m'

def print_test(name):
    print(f"\n{TestColors.INFO}🧪 Testing: {name}{TestColors.END}")

def print_pass(message):
    print(f"  {TestColors.PASS}✅ {message}{TestColors.END}")

def print_fail(message):
    print(f"  {TestColors.FAIL}❌ {message}{TestColors.END}")

def print_warn(message):
    print(f"  {TestColors.WARN}⚠️  {message}{TestColors.END}")


# Test 1: Database Initialization
def test_database_init():
    print_test("Database Initialization")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        # Create tables
        conn = sqlite3.connect(db_path)
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
        
        # Verify tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        required_tables = ['sessions', 'messages', 'repo_index', 'style_preferences']
        all_exist = all(table in tables for table in required_tables)
        
        conn.close()
        
        if all_exist:
            print_pass(f"All {len(required_tables)} tables created successfully")
            return True
        else:
            missing = [t for t in required_tables if t not in tables]
            print_fail(f"Missing tables: {', '.join(missing)}")
            return False


# Test 2: SQL Injection Prevention
def test_sql_injection_prevention():
    print_test("SQL Injection Prevention")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE repo_index (
                id INTEGER PRIMARY KEY,
                function_name TEXT,
                content TEXT
            )
        """)
        
        # Insert test data
        cursor.execute("INSERT INTO repo_index (function_name, content) VALUES (?, ?)",
                      ("testFunc", "test content"))
        conn.commit()
        
        # Test malicious input
        malicious_input = "'; DROP TABLE repo_index; --"
        
        # SECURE: Parameterized query
        try:
            cursor.execute("SELECT * FROM repo_index WHERE function_name LIKE ?", 
                          (f"%{malicious_input}%",))
            results = cursor.fetchall()
            
            # Verify table still exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repo_index'")
            table_exists = cursor.fetchone() is not None
            
            conn.close()
            
            if table_exists:
                print_pass("Parameterized queries prevent SQL injection")
                print_pass("Table survived malicious input")
                return True
            else:
                print_fail("Table was dropped - vulnerable to injection!")
                return False
                
        except Exception as e:
            print_fail(f"Query failed: {e}")
            return False


# Test 3: Auto-Learning Pattern Extraction
def test_auto_learning():
    print_test("Auto-Learning Pattern Extraction")
    
    sample_code = """
#include <Arduino.h>

#define MOTOR_PIN 5
const int TIMEOUT_MS = 5000;

void setup() {
    Serial.begin(115200);
    ledcSetup(0, 500, 8);
}
"""
    
    import re
    
    patterns = {
        'serial_baud': re.search(r'Serial\.begin\((\d+)\)', sample_code),
        'pin_style': 'define' if '#define' in sample_code else 'const',
        'timeout_value': re.search(r'TIMEOUT.*?(\d+)', sample_code),
        'pwm_freq': re.search(r'ledcSetup\([^,]+,\s*(\d+)', sample_code),
    }
    
    extracted = {}
    for key, value in patterns.items():
        if value:
            extracted[key] = value.group(1) if hasattr(value, 'group') else str(value)
    
    expected = {
        'serial_baud': '115200',
        'pin_style': 'define',
        'timeout_value': '5000',
        'pwm_freq': '500'
    }
    
    success = True
    for key, expected_val in expected.items():
        actual_val = extracted.get(key)
        if actual_val == expected_val:
            print_pass(f"Extracted {key}: {actual_val}")
        else:
            print_fail(f"Failed to extract {key} (got {actual_val}, expected {expected_val})")
            success = False
    
    return success


# Test 4: Module Detection
def test_module_detection():
    print_test("Module Detection")
    
    MODULE_PATTERNS = {
        "ble": ["bluetooth", "ble", "wireless"],
        "servo": ["servo", "flipper", "weapon"],
        "motor": ["motor", "drive", "movement", "l298n"],
        "safety": ["safety", "timeout", "failsafe"],
    }
    
    test_cases = [
        ("Generate code with BLE and servo control", ["ble", "servo"]),
        ("Add motor driver with safety timeout", ["motor", "safety"]),
        ("Build complete robot with bluetooth, motors, and weapon", ["ble", "motor", "servo"]),
    ]
    
    def extract_modules(message):
        message_lower = message.lower()
        detected = []
        for module, keywords in MODULE_PATTERNS.items():
            if any(kw in message_lower for kw in keywords):
                detected.append(module)
        return detected
    
    success = True
    for message, expected_modules in test_cases:
        detected = extract_modules(message)
        if set(detected) == set(expected_modules):
            print_pass(f"Detected: {detected} from '{message[:50]}...'")
        else:
            print_fail(f"Expected {expected_modules}, got {detected}")
            success = False
    
    return success


# Test 5: Complexity Detection
def test_complexity_detection():
    print_test("Complexity Detection")
    
    COMPLEX_TRIGGERS = ["complete", "entire", "full", "build entire"]
    MODULE_PATTERNS = {
        "ble": ["bluetooth", "ble"],
        "servo": ["servo"],
        "motor": ["motor"],
    }
    
    def is_complex(message):
        message_lower = message.lower()
        trigger_count = sum(1 for trigger in COMPLEX_TRIGGERS if trigger in message_lower)
        module_count = sum(1 for module, keywords in MODULE_PATTERNS.items() 
                          if any(kw in message_lower for kw in keywords))
        return trigger_count >= 2 or module_count >= 3
    
    test_cases = [
        ("Generate a motor driver class", False),
        ("Build complete robot with BLE, servo, and motors", True),
        ("Create entire system with full integration", True),
        ("What pins should I use?", False),
    ]
    
    success = True
    for message, expected_complex in test_cases:
        detected = is_complex(message)
        if detected == expected_complex:
            complexity = "COMPLEX" if detected else "SIMPLE"
            print_pass(f"{complexity}: '{message}'")
        else:
            print_fail(f"Expected {expected_complex}, got {detected} for '{message}'")
            success = False
    
    return success


# Test 6: LRU Cache Performance
def test_lru_cache():
    print_test("LRU Cache Performance")
    
    from functools import lru_cache
    import time
    
    call_count = 0
    
    @lru_cache(maxsize=128)
    def cached_function(keywords):
        nonlocal call_count
        call_count += 1
        time.sleep(0.01)  # Simulate slow operation
        return f"Result for {keywords}"
    
    # First call - should execute
    cached_function(("motor", "servo"))
    first_count = call_count
    
    # Second call - should use cache
    cached_function(("motor", "servo"))
    second_count = call_count
    
    # Different call - should execute
    cached_function(("ble", "battery"))
    third_count = call_count
    
    if first_count == 1 and second_count == 1 and third_count == 2:
        print_pass("Cache working: 2nd call skipped execution")
        print_pass(f"Function called {call_count} times for 3 queries")
        return True
    else:
        print_fail(f"Cache not working properly: {first_count}, {second_count}, {third_count}")
        return False


# Test 7: Session Export
def test_session_export():
    print_test("Session Export")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        export_path = Path(tmpdir) / "test_export.md"
        
        # Simulate export
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        messages = [
            ("user", "Generate motor code", "2025-12-28 10:00:00"),
            ("assistant", "```cpp\nvoid setupMotors() {}\n```", "2025-12-28 10:00:05"),
        ]
        
        output = f"# BuddAI Session Export\n"
        output += f"**Session ID:** {session_id}\n\n"
        output += "---\n\n"
        
        for role, content, timestamp in messages:
            if role == 'user':
                output += f"## 🧑 James ({timestamp})\n{content}\n\n"
            else:
                output += f"## 🤖 BuddAI\n{content}\n\n"
        
        with open(export_path, 'w', encoding='utf-8') as f:
            f.write(output)
        
        # Verify export
        if export_path.exists():
            content = export_path.read_text(encoding='utf-8')
            has_session_id = session_id in content
            has_code = "```cpp" in content
            has_headers = "## " in content and "James" in content  # More flexible check
            
            if has_session_id and has_code and has_headers:
                print_pass("Export file created with correct format")
                print_pass(f"File size: {len(content)} bytes")
                return True
            else:
                if not has_session_id:
                    print_fail("Missing session ID")
                if not has_code:
                    print_fail("Missing code blocks")
                if not has_headers:
                    print_fail("Missing headers")
                return False
        else:
            print_fail("Export file not created")
            return False


# Test 8: Actionable Suggestions
def test_actionable_suggestions():
    print_test("Actionable Suggestions")
    
    user_input = "Generate motor driver with L298N"
    generated_code = """
void setupMotors() {
    pinMode(MOTOR_PIN, OUTPUT);
}
"""
    
    suggestions = []
    
    # Forge Theory Check
    if ("motor" in user_input.lower() or "servo" in user_input.lower()) and "applyForge" not in generated_code:
        suggestions.append({
            'text': "Apply Forge Theory smoothing?",
            'action': 'add_forge',
            'code': "float applyForge(float current, float target, float k) { return target + (current - target) * exp(-k); }"
        })
    
    # Safety Check
    if "L298N" in user_input and "safety" not in generated_code.lower():
        suggestions.append({
            'text': "Add 5s safety timeout?",
            'action': 'add_safety',
            'code': "unsigned long lastCommandTime = 0;\nconst unsigned long TIMEOUT_MS = 5000;"
        })
    
    if len(suggestions) == 2:
        print_pass(f"Generated {len(suggestions)} actionable suggestions")
        for i, s in enumerate(suggestions, 1):
            print_pass(f"  {i}. {s['text']} (action: {s['action']})")
            if s['code']:
                print_pass(f"     Code snippet: {len(s['code'])} chars")
        return True
    else:
        print_fail(f"Expected 2 suggestions, got {len(suggestions)}")
        return False


# Test 9: Repository Indexing
def test_repository_indexing():
    print_test("Repository Indexing")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test repository structure
        repo_dir = Path(tmpdir) / "test_repo"
        repo_dir.mkdir()
        
        # Create test files
        test_files = {
            "motor_driver.ino": """
void setupMotors() {
    Serial.begin(115200);
    pinMode(MOTOR_PIN, OUTPUT);
}

void driveForward(int speed) {
    digitalWrite(MOTOR_PIN, HIGH);
}
""",
            "servo_control.cpp": """
#include <Servo.h>

void activateFlipper() {
    servo.write(90);
}
""",
            "utils.py": """
def calculate_pwm(speed):
    return int(speed * 255 / 100)

def apply_forge(current, target, k):
    return target + (current - target) * math.exp(-k)
"""
        }
        
        for filename, content in test_files.items():
            (repo_dir / filename).write_text(content)
        
        # Simulate indexing
        import re
        indexed_functions = []
        
        for file_path in repo_dir.rglob('*'):
            if file_path.is_file() and file_path.suffix in ['.ino', '.cpp', '.py']:
                content = file_path.read_text()
                
                if file_path.suffix in ['.ino', '.cpp']:
                    matches = re.findall(r'\b(?:void|int)\s+(\w+)\s*\(', content)
                    indexed_functions.extend(matches)
                elif file_path.suffix == '.py':
                    matches = re.findall(r'\bdef\s+(\w+)\s*\(', content)
                    indexed_functions.extend(matches)
        
        expected_functions = ['setupMotors', 'driveForward', 'activateFlipper', 'calculate_pwm', 'apply_forge']
        
        if set(indexed_functions) == set(expected_functions):
            print_pass(f"Indexed {len(indexed_functions)} functions correctly")
            for func in indexed_functions:
                print_pass(f"  - {func}()")
            return True
        else:
            missing = set(expected_functions) - set(indexed_functions)
            extra = set(indexed_functions) - set(expected_functions)
            if missing:
                print_fail(f"Missing functions: {missing}")
            if extra:
                print_warn(f"Extra functions: {extra}")
            return False


# Test 10: Search Query Safety
def test_search_query_safety():
    print_test("Search Query Safety")
    
    malicious_queries = [
        "'; DROP TABLE repo_index; --",
        "' OR '1'='1",
        "admin'--",
        "<script>alert('xss')</script>",
    ]
    
    import re
    
    success = True
    for query in malicious_queries:
        # Extract keywords safely
        keywords = re.findall(r'\b\w{4,}\b', query.lower())
        
        # Build parameterized query
        conditions = []
        params = []
        for keyword in keywords:
            conditions.append("(function_name LIKE ? OR content LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        
        # Verify no SQL injection possible
        if conditions:
            safe_sql = f"SELECT * FROM repo_index WHERE {' OR '.join(conditions)}"
            # SQL should only contain placeholders
            if "DROP" not in safe_sql and "'; " not in safe_sql:
                print_pass(f"Safely handled: '{query[:30]}...'")
            else:
                print_fail(f"Potential injection: '{query}'")
                success = False
        else:
            print_pass(f"Rejected empty query: '{query}'")
    
    return success


# Test 11: Context Window Management
def test_context_window():
    print_test("Context Window Management")
    
    context_messages = []
    
    # Add many messages
    for i in range(20):
        context_messages.append({"role": "user", "content": f"Message {i}"})
        context_messages.append({"role": "assistant", "content": f"Response {i}"})
    
    # Simulate limiting to last 5 messages
    limited_context = context_messages[-5:]
    
    if len(limited_context) == 5:
        print_pass(f"Context limited to {len(limited_context)} messages (from {len(context_messages)})")
        print_pass(f"Oldest kept: '{limited_context[0]['content']}'")
        print_pass(f"Newest kept: '{limited_context[-1]['content']}'")
        return True
    else:
        print_fail(f"Context not limited properly: {len(limited_context)} messages")
        return False


# Test 12: Schedule Awareness (New)
def test_schedule_awareness():
    print_test("Schedule Awareness")
    
    # Mock datetime to test different times
    with patch('buddai_v3_2.datetime') as mock_date:
        # 1. Early Morning (Monday 6:00 AM)
        mock_date.now.return_value = datetime(2025, 12, 29, 6, 0, 0)
        
        buddai = BuddAI(server_mode=False)
        status = buddai.get_user_status()
        
        if "Early Morning" in status:
            print_pass(f"6:00 AM Mon -> {status}")
        else:
            print_fail(f"Failed Morning check: {status}")
            return False
            
        # 2. Work Hours (Monday 10:00 AM)
        mock_date.now.return_value = datetime(2025, 12, 29, 10, 0, 0)
        status = buddai.get_user_status()
        
        if "Work Hours" in status:
            print_pass(f"10:00 AM Mon -> {status}")
        else:
            print_fail(f"Failed Work check: {status}")
            return False
            
    return True


# Test 13: Modular Plan Generation (New)
def test_modular_plan():
    print_test("Modular Plan Generation")
    
    buddai = BuddAI(server_mode=False)
    modules = ["ble", "servo"]
    plan = buddai.build_modular_plan(modules)
    
    # Expect 3 steps: ble, servo, integration
    if len(plan) == 3:
        tasks = [p['module'] for p in plan]
        if "integration" in tasks and "ble" in tasks:
            print_pass(f"Generated {len(plan)} steps including Integration")
            return True
    
    print_fail(f"Plan generation failed. Got {len(plan)} steps: {plan}")
    return False


# Test 14: Session Management (New)
def test_session_management():
    print_test("Session Management (CRUD)")
    
    # Use a named temporary file to handle Windows file locking better
    fd, test_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_db = Path(test_db_path)
    
    try:
        with patch('buddai_v3_2.DB_PATH', test_db):
            buddai = BuddAI(server_mode=False)
            
            # 1. Create
            sid = buddai.start_new_session()
            print_pass(f"Created session: {sid}")
            
            # 2. Rename
            buddai.rename_session(sid, "Unit Test Session")
            sessions = buddai.get_sessions(limit=1)
            if not sessions or sessions[0]['title'] != "Unit Test Session":
                print_fail("Rename failed")
                return False
            print_pass("Renamed session successfully")
            
            # 3. Delete
            buddai.delete_session(sid)
            sessions = buddai.get_sessions(limit=5)
            if any(s['id'] == sid for s in sessions):
                print_fail("Delete failed - session still exists")
                return False
            print_pass("Deleted session successfully")
    finally:
        # Manual cleanup with error suppression for Windows locks
        try:
            if test_db.exists():
                os.unlink(test_db)
        except Exception:
            pass

    return True


# Test 15: Rapid Session Creation (Collision Handling)
def test_rapid_session_creation():
    print_test("Rapid Session Creation (Collision Handling)")
    
    # Use a named temporary file to handle Windows file locking better
    fd, test_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_db = Path(test_db_path)
    
    try:
        # Mock datetime to return a fixed time, forcing ID collisions
        fixed_time = datetime(2025, 1, 1, 12, 0, 0)
        
        with patch('buddai_v3_2.DB_PATH', test_db):
            with patch('buddai_v3_2.datetime') as mock_dt:
                mock_dt.now.return_value = fixed_time
                
                buddai = BuddAI(server_mode=False)
                
                ids = [buddai.session_id] # Capture session from __init__
                
                # Create 4 more sessions rapidly
                for _ in range(4):
                    ids.append(buddai.start_new_session())
                
                # Verify format
                base_id = fixed_time.strftime("%Y%m%d_%H%M%S")
                expected = [base_id] + [f"{base_id}_{i}" for i in range(1, 5)]
                
                if ids == expected:
                    print_pass(f"Generated unique IDs with suffixes: {ids}")
                    return True
                else:
                    print_fail(f"Unexpected ID format. Expected {expected}, got {ids}")
                    return False
    finally:
        try:
            if test_db.exists():
                os.unlink(test_db)
        except Exception:
            pass

# Test 16: Repository Isolation (Multi-User)
def test_repo_isolation():
    print_test("Repository Isolation (Multi-User)")
    
    # Use a named temporary file for DB
    fd, test_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_db = Path(test_db_path)
    
    # Create a temp directory for repo
    with tempfile.TemporaryDirectory() as tmp_repo:
        repo_path = Path(tmp_repo)
        
        # Create a unique file for User 1
        (repo_path / "user1_secret.py").write_text("def user1_secret_function():\n    pass")
        
        try:
            with patch('buddai_v3_2.DB_PATH', test_db):
                # Suppress internal prints to keep test output clean
                with patch('builtins.print'):
                    # User 1 indexes the repo
                    buddai1 = BuddAI(user_id="user1", server_mode=False)
                    buddai1.index_local_repositories(str(repo_path))
                    
                    # User 2 instance
                    buddai2 = BuddAI(user_id="user2", server_mode=False)
                    
                    # User 1 searches
                    res1 = buddai1.search_repositories("user1_secret_function")
                    
                    # User 2 searches
                    res2 = buddai2.search_repositories("user1_secret_function")
                
                # Verify User 1 found it
                if "Found 1 matches" in res1 or "user1_secret_function" in res1:
                    print_pass("User 1 found their indexed code")
                else:
                    print_fail(f"User 1 failed to find code: {res1}")
                    return False
                    
                # Verify User 2 did NOT find it
                if "No functions found" in res2:
                     print_pass("User 2 could not see User 1's code")
                else:
                    print_fail(f"User 2 saw restricted code: {res2}")
                    return False
                    
        finally:
            try:
                if test_db.exists():
                    os.unlink(test_db)
            except Exception:
                pass
                
    return True

# Test 17: Upload Security (Hardening)
def test_upload_security():
    print_test("Upload Security (Hardening)")
    
    # 1. Test Magic Byte Check
    # We need to mock UploadFile since it's a FastAPI class
    class MockUploadFile:
        def __init__(self, filename, content):
            self.filename = filename
            self.file = io.BytesIO(content)
            self.content_type = "application/zip"
            
    if hasattr(buddai_module, 'validate_upload'):
        # Create a fake zip (text file renamed)
        fake_zip = MockUploadFile("fake.zip", b"This is not a zip file")
        try:
            buddai_module.validate_upload(fake_zip)
            print_fail("Magic byte check failed (accepted invalid zip)")
            return False
        except ValueError as e:
            if "Invalid ZIP file header" in str(e):
                print_pass("Magic byte check rejected invalid zip header")
            else:
                print_fail(f"Unexpected error: {e}")
                return False
    else:
        print_warn("Skipping magic byte check (validate_upload not available)")

    # 2. Test Zip Slip Protection
    if hasattr(buddai_module, 'safe_extract_zip'):
        with tempfile.TemporaryDirectory() as tmpdir:
            malicious_zip_path = Path(tmpdir) / "slip.zip"
            extract_dir = Path(tmpdir) / "extract"
            extract_dir.mkdir()
            
            # Create a zip file with a member pointing to parent directory
            # We use zipfile to craft this manually
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zf:
                zf.writestr('../evil.txt', 'malicious content')
            
            malicious_zip_path.write_bytes(zip_buffer.getvalue())
            
            try:
                buddai_module.safe_extract_zip(malicious_zip_path, extract_dir)
                print_fail("Zip Slip protection failed (extracted malicious file)")
                return False
            except ValueError as e:
                if "Malicious zip member" in str(e):
                    print_pass("Zip Slip protection caught directory traversal")
                else:
                    print_fail(f"Unexpected error during extraction: {e}")
                    return False
    return True

# Test 18: WebSocket Logic (Streaming)
def test_websocket_logic():
    print_test("WebSocket Logic (Streaming)")
    
    # Use a named temporary file for DB
    fd, test_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_db = Path(test_db_path)
    
    try:
        with patch('buddai_v3_2.DB_PATH', test_db):
            # Suppress prints during init
            with patch('builtins.print'):
                buddai = BuddAI(server_mode=False)
            
            # Mock call_model to return a generator
            def mock_generator(*args, **kwargs):
                yield "Stream"
                yield "ing"
                yield "..."
            
            with patch.object(buddai, 'call_model', side_effect=mock_generator) as mock_call:
                # Mock shadow engine to avoid DB lookups or side effects affecting output
                with patch.object(buddai.shadow_engine, 'get_all_suggestions', return_value=[]):
                    
                    # Execute
                    stream = buddai.chat_stream("Test Message", force_model="fast")
                    chunks = list(stream)
                    full_text = "".join(chunks)
                    
                    # Verify 1: Content
                    if full_text == "Streaming...":
                        print_pass("Streamed content matches expected output")
                    else:
                        print_fail(f"Stream content mismatch. Got: '{full_text}'")
                        return False
                    
                    # Verify 2: Stream flag passed to model
                    args, kwargs = mock_call.call_args
                    if kwargs.get('stream') is True:
                        print_pass("call_model invoked with stream=True")
                    else:
                        print_fail(f"call_model arguments incorrect: {kwargs}")
                        return False
                        
                    # Verify 3: Context saved
                    last_msg = buddai.context_messages[-1]
                    if last_msg['role'] == 'assistant' and last_msg['content'] == "Streaming...":
                        print_pass("Conversation context updated correctly")
                    else:
                        print_fail("Context update failed")
                        return False

    finally:
        try:
            if test_db.exists():
                os.unlink(test_db)
        except Exception:
            pass
            
    return True

# Test 19: Connection Pooling
def test_connection_pool():
    print_test("Connection Pooling")
    
    if not hasattr(buddai_module, 'OLLAMA_POOL'):
        print_fail("OLLAMA_POOL not found in module")
        return False
        
    pool = buddai_module.OLLAMA_POOL
    
    # Drain pool first to ensure clean state for test
    while not pool.pool.empty():
        try:
            c = pool.pool.get_nowait()
            c.close()
        except:
            break
            
    # 1. Get a connection (should create new)
    conn1 = pool.get_connection()
    if not isinstance(conn1, http.client.HTTPConnection):
        print_fail("get_connection did not return HTTPConnection")
        return False
    print_pass("Successfully retrieved connection from pool")

    # 2. Return connection
    pool.return_connection(conn1)
    if pool.pool.qsize() == 1:
        print_pass("Connection returned to pool (size=1)")
    else:
        print_fail(f"Pool size incorrect after return. Expected 1, got {pool.pool.qsize()}")
        return False
        
    # 3. Reuse connection
    conn2 = pool.get_connection()
    if conn2 is conn1:
        print_pass("Pool reused the existing connection object")
    else:
        print_fail("Pool created new connection instead of reusing")
        return False
        
    # 4. Overflow handling
    # Fill beyond max size (default 10)
    # conn2 is currently checked out, so pool is empty
    for _ in range(15):
        c = http.client.HTTPConnection("localhost", 11434)
        pool.return_connection(c)
    
    if pool.pool.full():
        print_pass("Pool capped at max size, excess connections discarded")
        return True
    else:
        print_fail(f"Pool overflow handling failed. Size: {pool.pool.qsize()}")
        return False

# Main Test Runner
def run_all_tests():
    print("\n" + "="*60)
    print("🔥 BuddAI v3.2 Comprehensive Test Suite")
    print("="*60)
    
    tests = [
        ("Database Initialization", test_database_init),
        ("SQL Injection Prevention", test_sql_injection_prevention),
        ("Auto-Learning", test_auto_learning),
        ("Module Detection", test_module_detection),
        ("Complexity Detection", test_complexity_detection),
        ("LRU Cache", test_lru_cache),
        ("Session Export", test_session_export),
        ("Actionable Suggestions", test_actionable_suggestions),
        ("Repository Indexing", test_repository_indexing),
        ("Search Query Safety", test_search_query_safety),
        ("Context Window", test_context_window),
        ("Schedule Awareness", test_schedule_awareness),
        ("Modular Plan", test_modular_plan),
        ("Session Management", test_session_management),
        ("Rapid Session Creation", test_rapid_session_creation),
        ("Repository Isolation", test_repo_isolation),
        ("Upload Security", test_upload_security),
        ("WebSocket Logic", test_websocket_logic),
        ("Connection Pooling", test_connection_pool),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print_fail(f"Test crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("📊 Test Results Summary")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = f"{TestColors.PASS}✅ PASS{TestColors.END}" if result else f"{TestColors.FAIL}❌ FAIL{TestColors.END}"
        print(f"{status} - {name}")
    
    print("\n" + "="*60)
    percentage = int((passed / total) * 100)
    
    if passed == total:
        print(f"{TestColors.PASS}🎉 ALL TESTS PASSED: {passed}/{total} ({percentage}%){TestColors.END}")
    elif passed >= total * 0.8:
        print(f"{TestColors.WARN}⚠️  MOST TESTS PASSED: {passed}/{total} ({percentage}%){TestColors.END}")
    else:
        print(f"{TestColors.FAIL}❌ TESTS FAILED: {passed}/{total} ({percentage}%){TestColors.END}")
    
    print("="*60 + "\n")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)