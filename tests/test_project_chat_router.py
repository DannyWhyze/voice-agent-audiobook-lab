from fastapi.testclient import TestClient

from src.orchestrator.agents import project_chat_agent
from src.orchestrator.main import app
from src.orchestrator.routers import chat as chat_router

client = TestClient(app)

VOICES_MESSAGE = {
    "role": "system",
    "content": (
        "Verfügbare Stimmen in diesem Projekt: Erzähler, Held. Verwende "
        "ausschließlich diese Namen oder 'base_voice' für einen Sprecher ohne "
        "bestimmte Stimme — niemals andere oder erfundene Namen."
    ),
}


class _FakeChunk:
    def __init__(self, content, reasoning=None):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}


class _StreamingFakeAgent:
    def __init__(self, chunks):
        self._chunks = chunks
        self.received_messages = None

    async def astream_events(self, input_, version="v2"):
        self.received_messages = input_["messages"]
        for text in self._chunks:
            yield {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk(text)}}


class _FailFastAgent:
    async def astream_events(self, input_, version="v2"):
        raise ConnectionError("no ollama")
        yield  # pragma: no cover - makes this an async generator function


class _MidStreamFailAgent:
    async def astream_events(self, input_, version="v2"):
        yield {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("Hal")}}
        raise ConnectionError("dropped")


def test_project_chat_route_streams_chunks(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler", "Held"])
    fake = _StreamingFakeAgent(["Hel", "lo"])
    monkeypatch.setattr(project_chat_agent, "_build_agent", lambda proj, p, m: fake)

    response = client.post(
        "/projects/P/chat",
        json={"messages": [{"role": "user", "content": "Hallo"}]},
    )

    assert response.status_code == 200
    body = response.text
    assert 'data: {"chunk": "Hel"}' in body
    assert 'data: {"chunk": "lo"}' in body
    assert body.strip().endswith("event: done\ndata: {}")
    assert fake.received_messages == [
        VOICES_MESSAGE,
        {"role": "user", "content": "Hallo"},
    ]


def test_project_chat_route_passes_project_from_url(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    captured = {}

    def _fake_build(project, provider, model):
        captured["project"] = project
        return _StreamingFakeAgent(["Hi"])

    monkeypatch.setattr(project_chat_agent, "_build_agent", _fake_build)

    response = client.post("/projects/MyProject/chat", json={"messages": []})

    assert response.status_code == 200
    assert captured == {"project": "MyProject"}


def test_project_chat_route_returns_503_when_agent_fails_before_first_chunk(
    monkeypatch,
):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.setattr(
        project_chat_agent, "_build_agent", lambda proj, p, m: _FailFastAgent()
    )

    response = client.post("/projects/P/chat", json={"messages": []})

    assert response.status_code == 503
    assert "no ollama" in response.json()["detail"]


def test_project_chat_route_emits_error_event_after_partial_stream(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.setattr(
        project_chat_agent, "_build_agent", lambda proj, p, m: _MidStreamFailAgent()
    )

    response = client.post("/projects/P/chat", json={"messages": []})

    assert response.status_code == 200
    body = response.text
    assert 'data: {"chunk": "Hal"}' in body
    assert "event: error" in body
    assert "dropped" in body
    assert "event: done" not in body


def test_project_chat_route_returns_400_for_nvidia_without_api_key(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    response = client.post(
        "/projects/P/chat",
        json={
            "messages": [],
            "provider": "nvidia",
            "model": "meta/llama-3.3-70b-instruct",
        },
    )

    assert response.status_code == 400
    assert "NVIDIA_API_KEY" in response.json()["detail"]
