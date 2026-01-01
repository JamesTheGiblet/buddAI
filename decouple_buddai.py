import os
import re

def decouple_exocortex(source_file):
    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define the file splits based on class/block signatures
    splits = {
        "buddai_memory.py": ["class ShadowSuggestionEngine", "class AdaptiveLearner", "class SmartLearner"],
        "buddai_logic.py": ["class CodeValidator", "class HardwareProfile", "class LearningMetrics"],
        "buddai_executive.py": ["class OllamaConnectionPool", "class BuddAI", "class ModelFineTuner"],
        "buddai_server.py": ["if SERVER_AVAILABLE:", "app = FastAPI", "class BuddAIManager"]
    }

    print(f"🚀 Surgical extraction of {source_file} initiated...")

    # Extraction logic for classes/blocks
    for filename, markers in splits.items():
        extracted_sections = []
        for marker in markers:
            # Simple extraction based on class indentation/block end
            pattern = re.compile(rf"{re.escape(marker)}.*?(?=\nclass |\nif __name__ ==|\nif SERVER_AVAILABLE)", re.DOTALL)
            match = pattern.search(content)
            if match:
                extracted_sections.append(match.group(0))
        
        if extracted_sections:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("#!/usr/bin/env python3\n")
                f.write("import sys, os, json, logging, sqlite3, datetime, pathlib, http.client, re, typing, zipfile, shutil, queue, socket, argparse, io, difflib\n")
                f.write("from pathlib import Path\nfrom datetime import datetime, timedelta\nfrom typing import Optional, List, Dict, Tuple, Union, Generator\n\n")
                f.write("try:\n    from fastapi import FastAPI, File, Header, Response, UploadFile, WebSocketDisconnect, Request, WebSocket\n    from fastapi.middleware.cors import CORSMiddleware\n    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse\n    from fastapi.staticfiles import StaticFiles\n    from pydantic import BaseModel\n    import uvicorn\nexcept ImportError:\n    pass\n\n")
                f.write("\n\n".join(extracted_sections))
            print(f"✅ Created {filename}")

if __name__ == "__main__":
    # Use the script's directory to find main.py reliably
    source_path = os.path.join(os.path.dirname(__file__), "main.py")
    if os.path.exists(source_path):
        decouple_exocortex(source_path)
    else:
        print(f"❌ Error: Could not find {source_path}")