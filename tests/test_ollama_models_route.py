from fastapi.testclient import TestClient

from src.orchestrator.main import app
from src.orchestrator.routers import chat as chat_router

client = TestClient(app)


def test_ollama_models_route_returns_fetched_models(monkeypatch):
    monkeypatch.setattr(
        chat_router,
        "fetch_ollama_models",
        lambda: [{"id": "qwen3.5:latest", "type": "chat"}],
    )
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    response = client.get("/api/llm/ollama-models")

    assert response.status_code == 200
    assert response.json() == {
        "models": [{"id": "qwen3.5:latest", "type": "chat"}],
        "default_model": None,
    }


def test_ollama_models_route_returns_empty_list_when_ollama_unreachable(monkeypatch):
    monkeypatch.setattr(chat_router, "fetch_ollama_models", list)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    response = client.get("/api/llm/ollama-models")

    assert response.status_code == 200
    assert response.json() == {"models": [], "default_model": None}


def test_ollama_models_route_reports_configured_default_model(monkeypatch):
    monkeypatch.setattr(chat_router, "fetch_ollama_models", list)
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")

    response = client.get("/api/llm/ollama-models")

    assert response.status_code == 200
    assert response.json() == {"models": [], "default_model": "gemma4:12b"}
