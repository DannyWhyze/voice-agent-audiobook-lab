import pytest
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_ollama import ChatOllama

from src.orchestrator.agents.llm_provider import build_chat_model


def test_ollama_provider_uses_default_model_when_none_given():
    result = build_chat_model("ollama", None, "qwen3.5:latest")
    assert isinstance(result, ChatOllama)
    assert result.model == "qwen3.5:latest"


def test_ollama_provider_uses_explicit_model_over_default():
    result = build_chat_model("ollama", "gemma4:12b", "qwen3.5:latest")
    assert isinstance(result, ChatOllama)
    assert result.model == "gemma4:12b"


def test_ollama_provider_raises_without_model_or_default():
    with pytest.raises(ValueError, match="No Ollama model selected"):
        build_chat_model("ollama", None, None)


def test_nvidia_provider_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        build_chat_model("nvidia", "meta/llama-3.3-70b-instruct", "qwen3.5:latest")


def test_nvidia_provider_raises_without_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    with pytest.raises(ValueError, match="model is required"):
        build_chat_model("nvidia", None, "qwen3.5:latest")


def test_nvidia_provider_builds_chat_nvidia(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    result = build_chat_model("nvidia", "meta/llama-3.3-70b-instruct", "qwen3.5:latest")
    assert isinstance(result, ChatNVIDIA)
