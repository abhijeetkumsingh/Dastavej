"""Starts DASTAVEJ for UI tests with a fake Gemini reply (never used in production)."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import create_app
from app.services import gemini_service as gs

tmp = Path(tempfile.mkdtemp())
app = create_app({"STORAGE_DIR": tmp / "s", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp / 'ui.db'}", "RATELIMIT_ENABLED": False,
                  "SECRET_KEY": "ui-test", "ENABLE_CLEANUP_THREAD": False, "GEMINI_API_KEY": "fake"})
gs.generate = lambda system, prompt: json.dumps({"answer": "The total is 1550 [S1].", "confidence": "high", "uncertainty": "",
                                                  "used_sources": [1], "calculations": [{"expression": "1200+350", "claimed_result": 1550}]})
app.run(port=int(sys.argv[1]), threaded=True)
