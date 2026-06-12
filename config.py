"""Centralized configuration — loads secrets from .env file."""

import os
import sys
from pathlib import Path

# ── Load .env file ───────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── OpenRouter API ───────────────────────────────────────────────────
OPENROUTER_API_KEY = "ollama"   # Ollama ignores the key; any string works
OPENROUTER_MODEL   = "qwen2.5:7b"
OPENROUTER_URL     = "http://localhost:11434/v1/chat/completions"


def require_api_key():
    """Check Ollama is reachable before starting."""
    import requests
    try:
        r = requests.get("http://localhost:11434", timeout=3)
        if r.status_code != 200:
            raise ConnectionError()
    except Exception:
        print("ERROR: Ollama is not running.")
        print("  Start it with:  ollama serve")
        print("  Pull a model :  ollama pull qwen2.5:7b")
        sys.exit(1)
