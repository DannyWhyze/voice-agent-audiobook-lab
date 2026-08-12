from src.orchestrator.utils import verify_nvidia_models


class _FakeChatNVIDIA:
    def __init__(self, model, max_completion_tokens=1, **kwargs):
        self.model = model

    def invoke(self, prompt):
        if self.model == "broken/model":
            raise RuntimeError("410 EOL")
        return "ok"


def test_filters_out_models_that_fail_the_live_probe(monkeypatch):
    monkeypatch.setattr(
        verify_nvidia_models,
        "fetch_nvidia_models",
        lambda api_key=None: [
            {"id": "good/model", "type": "chat"},
            {"id": "broken/model", "type": "chat"},
        ],
    )
    monkeypatch.setattr(verify_nvidia_models, "ChatNVIDIA", _FakeChatNVIDIA)

    result = verify_nvidia_models.fetch_verified_nvidia_models()

    assert result == [{"id": "good/model", "type": "chat"}]


def test_returns_empty_list_when_no_raw_models(monkeypatch):
    monkeypatch.setattr(
        verify_nvidia_models, "fetch_nvidia_models", lambda api_key=None: []
    )

    assert verify_nvidia_models.fetch_verified_nvidia_models() == []
