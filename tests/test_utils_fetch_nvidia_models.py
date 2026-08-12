import langchain_nvidia_ai_endpoints

from src.orchestrator.utils.fetch_nvidia_models import fetch_nvidia_models


class _FakeModel:
    def __init__(self, id, model_type="chat", deprecated=False, supports_tools=True):
        self.id = id
        self.model_type = model_type
        self.deprecated = deprecated
        self.supports_tools = supports_tools


def test_returns_empty_list_when_no_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert fetch_nvidia_models(api_key=None) == []


def test_filters_deprecated_non_chat_and_non_tool_models(monkeypatch):
    fake_models = [
        _FakeModel("good/model"),
        _FakeModel("deprecated/model", deprecated=True),
        _FakeModel("embedding/model", model_type="embedding"),
        _FakeModel("no-tools/model", supports_tools=False),
    ]
    monkeypatch.setattr(
        langchain_nvidia_ai_endpoints.ChatNVIDIA,
        "get_available_models",
        lambda **kwargs: fake_models,
    )

    result = fetch_nvidia_models(api_key="nvapi-test")

    assert [m["id"] for m in result] == ["good/model"]


def test_filters_known_eol_models_even_if_not_flagged_deprecated(monkeypatch):
    fake_models = [
        _FakeModel("good/model"),
        _FakeModel("moonshotai/kimi-k2-instruct"),
    ]
    monkeypatch.setattr(
        langchain_nvidia_ai_endpoints.ChatNVIDIA,
        "get_available_models",
        lambda **kwargs: fake_models,
    )

    result = fetch_nvidia_models(api_key="nvapi-test")

    assert [m["id"] for m in result] == ["good/model"]


def test_returns_empty_list_when_endpoint_raises(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        langchain_nvidia_ai_endpoints.ChatNVIDIA, "get_available_models", _boom
    )

    assert fetch_nvidia_models(api_key="nvapi-test") == []
