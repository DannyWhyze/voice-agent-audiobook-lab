from unittest.mock import MagicMock

import httpx

from src.orchestrator.utils import fetch_ollama_models as fetch_ollama_models_module
from src.orchestrator.utils.fetch_ollama_models import fetch_ollama_models


def test_filters_to_chat_capable_models(monkeypatch):
    mock_get = MagicMock()
    mock_get.return_value.json.return_value = {
        "models": [
            {"name": "qwen3.5:latest", "capabilities": ["completion", "tools"]},
            {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
            {"name": "gemma4:12b", "capabilities": ["completion", "vision"]},
        ]
    }
    monkeypatch.setattr(fetch_ollama_models_module.httpx, "get", mock_get)

    result = fetch_ollama_models()

    assert result == [
        {"id": "qwen3.5:latest", "type": "chat"},
        {"id": "gemma4:12b", "type": "chat"},
    ]


def test_returns_empty_list_when_ollama_unreachable(monkeypatch):
    def mock_get_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(fetch_ollama_models_module.httpx, "get", mock_get_connect_error)

    assert fetch_ollama_models() == []


def test_returns_empty_list_on_timeout(monkeypatch):
    def mock_get_timeout(*args, **kwargs):
        raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(fetch_ollama_models_module.httpx, "get", mock_get_timeout)

    assert fetch_ollama_models() == []


def test_returns_empty_list_with_no_models_installed(monkeypatch):
    mock_get = MagicMock()
    mock_get.return_value.json.return_value = {"models": []}
    monkeypatch.setattr(fetch_ollama_models_module.httpx, "get", mock_get)

    assert fetch_ollama_models() == []
