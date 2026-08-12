from fastapi.testclient import TestClient

from src.orchestrator.agents import script_chat_agent
from src.orchestrator.main import app
from src.orchestrator.routers import chat as chat_router

client = TestClient(app)


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


class _ReasoningFakeAgent:
    async def astream_events(self, input_, version="v2"):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": _FakeChunk("", reasoning="Denke nach...")},
        }
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": _FakeChunk("Antwort")},
        }


VOICES_MESSAGE = {
    "role": "system",
    "content": (
        "Verfügbare Stimmen in diesem Projekt: Erzähler, Held. Verwende "
        "ausschließlich diese Namen oder 'base_voice' für einen Sprecher ohne "
        "bestimmte Stimme — niemals andere oder erfundene Namen."
    ),
}

EMPTY_VOICES_MESSAGE = {
    "role": "system",
    "content": (
        "Aktuell sind keine Stimmen konfiguriert — verwende ausschließlich "
        "'base_voice' für alle Sprecher."
    ),
}


def test_script_chat_route_streams_chunks(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler", "Held"])
    fake = _StreamingFakeAgent(["Hel", "lo"])
    monkeypatch.setattr(script_chat_agent, "_build_agent", lambda proj, p, m, r: fake)

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={
            "current_text": "Erzähler: Hallo Welt\nHeld: Willkommen",
            "messages": [{"role": "user", "content": "Kürzer bitte"}],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert 'data: {"chunk": "Hel"}' in body
    assert 'data: {"chunk": "lo"}' in body
    assert body.strip().endswith("event: done\ndata: {}")
    assert fake.received_messages == [
        VOICES_MESSAGE,
        {
            "role": "system",
            "content": "Aktueller Text der Box: Erzähler: Hallo Welt\nHeld: Willkommen",
        },
        {"role": "user", "content": "Kürzer bitte"},
    ]


def test_script_chat_route_never_sends_script_context_message(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler", "Held"])
    fake = _StreamingFakeAgent(["Hi"])
    monkeypatch.setattr(script_chat_agent, "_build_agent", lambda proj, p, m, r: fake)

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={"current_text": "Erzähler: Text", "messages": []},
    )

    assert response.status_code == 200
    assert fake.received_messages == [
        VOICES_MESSAGE,
        {"role": "system", "content": "Aktueller Text der Box: Erzähler: Text"},
    ]


def test_script_chat_route_uses_empty_voices_message_when_no_voices_configured(
    monkeypatch,
):
    monkeypatch.setattr(chat_router, "list_active_voices", list)
    fake = _StreamingFakeAgent(["Hi"])
    monkeypatch.setattr(script_chat_agent, "_build_agent", lambda proj, p, m, r: fake)

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={"current_text": "base_voice: Text", "messages": []},
    )

    assert response.status_code == 200
    assert fake.received_messages == [
        EMPTY_VOICES_MESSAGE,
        {"role": "system", "content": "Aktueller Text der Box: base_voice: Text"},
    ]


def test_script_chat_route_returns_503_when_agent_fails_before_first_chunk(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.setattr(
        script_chat_agent, "_build_agent", lambda proj, p, m, r: _FailFastAgent()
    )

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 503
    assert "no ollama" in response.json()["detail"]


def test_script_chat_route_emits_error_event_after_partial_stream(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.setattr(
        script_chat_agent, "_build_agent", lambda proj, p, m, r: _MidStreamFailAgent()
    )

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 200
    body = response.text
    assert 'data: {"chunk": "Hal"}' in body
    assert "event: error" in body
    assert "dropped" in body
    assert "event: done" not in body


def test_script_chat_route_emits_reasoning_event(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.setattr(
        script_chat_agent, "_build_agent", lambda proj, p, m, r: _ReasoningFakeAgent()
    )

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 200
    body = response.text
    assert 'event: reasoning\ndata: {"chunk": "Denke nach..."}' in body
    assert 'data: {"chunk": "Antwort"}' in body
    assert 'event: reasoning\ndata: {"chunk": "Antwort"}' not in body
    assert body.strip().endswith("event: done\ndata: {}")


def test_script_chat_route_returns_400_for_nvidia_without_api_key(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={
            "current_text": "Text",
            "messages": [],
            "provider": "nvidia",
            "model": "meta/llama-3.3-70b-instruct",
        },
    )

    assert response.status_code == 400
    assert "NVIDIA_API_KEY" in response.json()["detail"]


def test_script_chat_route_passes_allow_extend_recorded_roles(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    captured = {}

    def _fake_build(project, provider, model, allow_extend_recorded_roles):
        captured["allow_extend_recorded_roles"] = allow_extend_recorded_roles
        return _StreamingFakeAgent(["Hi"])

    monkeypatch.setattr(script_chat_agent, "_build_agent", _fake_build)

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={
            "current_text": "Text",
            "messages": [],
            "allow_extend_recorded_roles": True,
        },
    )

    assert response.status_code == 200
    assert captured == {"allow_extend_recorded_roles": True}


def test_script_chat_route_defaults_allow_extend_recorded_roles_to_false(monkeypatch):
    monkeypatch.setattr(chat_router, "list_active_voices", lambda: ["Erzähler"])
    captured = {}

    def _fake_build(project, provider, model, allow_extend_recorded_roles):
        captured["allow_extend_recorded_roles"] = allow_extend_recorded_roles
        return _StreamingFakeAgent(["Hi"])

    monkeypatch.setattr(script_chat_agent, "_build_agent", _fake_build)

    response = client.post(
        "/projects/P/chapters/C/script-chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 200
    assert captured == {"allow_extend_recorded_roles": False}
