from fastapi.testclient import TestClient

from src.orchestrator.agents import chat_agent
from src.orchestrator.main import app

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


def test_chat_route_streams_chunks_and_sends_context(monkeypatch):
    fake = _StreamingFakeAgent(["Hel", "lo"])
    monkeypatch.setattr(chat_agent, "_build_agent", lambda proj, p, m: fake)

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={
            "current_text": "Hallo Welt",
            "messages": [{"role": "user", "content": "Kürzer bitte"}],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert 'data: {"chunk": "Hel"}' in body
    assert 'data: {"chunk": "lo"}' in body
    assert body.strip().endswith("event: done\ndata: {}")
    assert fake.received_messages == [
        {"role": "system", "content": "Aktueller Text der Box: Hallo Welt"},
        {"role": "user", "content": "Kürzer bitte"},
    ]


def test_chat_route_includes_script_context_when_provided(monkeypatch):
    fake = _StreamingFakeAgent(["Hi"])
    monkeypatch.setattr(chat_agent, "_build_agent", lambda proj, p, m: fake)

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={
            "current_text": "Box-Text",
            "context_text": "Erzähler: Zeile 1\nHeld: Zeile 2",
            "messages": [],
        },
    )

    assert response.status_code == 200
    assert fake.received_messages == [
        {
            "role": "system",
            "content": "Gesamtes Skript als Kontext: Erzähler: Zeile 1\nHeld: Zeile 2",
        },
        {"role": "system", "content": "Aktueller Text der Box: Box-Text"},
    ]


def test_chat_route_omits_script_context_message_when_not_provided(monkeypatch):
    fake = _StreamingFakeAgent(["Hi"])
    monkeypatch.setattr(chat_agent, "_build_agent", lambda proj, p, m: fake)

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={"current_text": "Box-Text", "messages": []},
    )

    assert response.status_code == 200
    assert fake.received_messages == [
        {"role": "system", "content": "Aktueller Text der Box: Box-Text"},
    ]


def test_chat_route_treats_empty_script_context_as_not_provided(monkeypatch):
    fake = _StreamingFakeAgent(["Hi"])
    monkeypatch.setattr(chat_agent, "_build_agent", lambda proj, p, m: fake)

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={"current_text": "Box-Text", "context_text": "", "messages": []},
    )

    assert response.status_code == 200
    assert fake.received_messages == [
        {"role": "system", "content": "Aktueller Text der Box: Box-Text"},
    ]


def test_chat_route_returns_503_when_agent_fails_before_first_chunk(monkeypatch):
    monkeypatch.setattr(chat_agent, "_build_agent", lambda proj, p, m: _FailFastAgent())

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 503
    assert "no ollama" in response.json()["detail"]


def test_chat_route_emits_error_event_after_partial_stream(monkeypatch):
    monkeypatch.setattr(
        chat_agent, "_build_agent", lambda proj, p, m: _MidStreamFailAgent()
    )

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 200
    body = response.text
    assert 'data: {"chunk": "Hal"}' in body
    assert "event: error" in body
    assert "dropped" in body
    assert "event: done" not in body


def test_chat_route_emits_reasoning_event(monkeypatch):
    monkeypatch.setattr(
        chat_agent, "_build_agent", lambda proj, p, m: _ReasoningFakeAgent()
    )

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={"current_text": "Text", "messages": []},
    )

    assert response.status_code == 200
    body = response.text
    assert 'event: reasoning\ndata: {"chunk": "Denke nach..."}' in body
    assert 'data: {"chunk": "Antwort"}' in body
    assert 'event: reasoning\ndata: {"chunk": "Antwort"}' not in body
    assert body.strip().endswith("event: done\ndata: {}")


def test_chat_route_returns_400_for_nvidia_without_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    response = client.post(
        "/projects/P/chapters/C/boxes/0/chat",
        json={
            "current_text": "Text",
            "messages": [],
            "provider": "nvidia",
            "model": "meta/llama-3.3-70b-instruct",
        },
    )

    assert response.status_code == 400
    assert "NVIDIA_API_KEY" in response.json()["detail"]
