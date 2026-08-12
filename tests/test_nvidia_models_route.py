import pytest
from fastapi.testclient import TestClient

from src.orchestrator.main import app
from src.orchestrator.routers import chat as chat_router

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_nvidia_models_cache():
    chat_router._nvidia_models_cache = None
    yield
    chat_router._nvidia_models_cache = None


def test_nvidia_models_route_returns_empty_list_when_no_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    response = client.get("/api/llm/nvidia-models")
    assert response.status_code == 200
    assert response.json() == {"models": []}


def test_nvidia_models_route_returns_verified_models(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    monkeypatch.setattr(
        chat_router,
        "fetch_verified_nvidia_models",
        lambda api_key=None: [{"id": "meta/llama-3.3-70b-instruct", "type": "chat"}],
    )
    response = client.get("/api/llm/nvidia-models")
    assert response.status_code == 200
    assert response.json() == {
        "models": [{"id": "meta/llama-3.3-70b-instruct", "type": "chat"}]
    }


def test_nvidia_models_route_caches_result_across_requests(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    call_count = 0

    def _fake_fetch(api_key=None):
        nonlocal call_count
        call_count += 1
        return [{"id": "meta/llama-3.3-70b-instruct", "type": "chat"}]

    monkeypatch.setattr(chat_router, "fetch_verified_nvidia_models", _fake_fetch)

    first = client.get("/api/llm/nvidia-models")
    second = client.get("/api/llm/nvidia-models")

    assert (
        first.json()
        == second.json()
        == {"models": [{"id": "meta/llama-3.3-70b-instruct", "type": "chat"}]}
    )
    assert call_count == 1


def test_nvidia_models_route_does_not_cache_empty_result_without_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    client.get("/api/llm/nvidia-models")

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    monkeypatch.setattr(
        chat_router,
        "fetch_verified_nvidia_models",
        lambda api_key=None: [{"id": "meta/llama-3.3-70b-instruct", "type": "chat"}],
    )
    response = client.get("/api/llm/nvidia-models")

    assert response.json() == {
        "models": [{"id": "meta/llama-3.3-70b-instruct", "type": "chat"}]
    }
