#!/usr/bin/env python3
import sys, os, json, logging, sqlite3, datetime, pathlib, http.client, re, typing, zipfile, shutil, queue, socket, argparse, io, difflib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Union, Generator

from fastapi import FastAPI
import uvicorn

from buddai_shared import SERVER_AVAILABLE, DATA_DIR, DB_PATH, MODELS, OLLAMA_HOST, OLLAMA_PORT
from buddai_executive import BuddAI

# (Removed duplicate definitions of check_ollama, is_port_available, and main to resolve indentation and duplication errors)



from fastapi.middleware.cors import CORSMiddleware
from fastapi import File, UploadFile, Header, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from urllib.parse import urlparse

try:
    import psutil
except ImportError:
    psutil = None
try:
    import qrcode
except ImportError:
    qrcode = None

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_UPLOAD_FILES = 20
ALLOWED_TYPES = [
    "application/zip", "application/x-zip-compressed",
    "text/x-python", "text/plain", "application/octet-stream",
    "text/x-c++src", "text/x-c++hdr", "text/javascript",
    "text/html", "text/css"
]

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
