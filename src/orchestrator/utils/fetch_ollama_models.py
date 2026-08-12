from __future__ import annotations

import httpx

OLLAMA_URL = "http://127.0.0.1:11434"


def fetch_ollama_models() -> list[dict]:
    """Fetches installed Ollama models, filtered to chat-capable ones."""
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
        response.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return []

    models = response.json().get("models", [])
    return [
        {"id": m["name"], "type": "chat"}
        for m in models
        if "completion" in m.get("capabilities", [])
    ]
