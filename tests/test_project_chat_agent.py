import asyncio

from src.orchestrator.agents import project_chat_agent


class _FakeChunk:
    def __init__(self, content, reasoning=None):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}


class _FakeAgent:
    def __init__(self, events):
        self._events = events
        self.received_input = None

    async def astream_events(self, input_, version="v2"):
        self.received_input = input_
        for event in self._events:
            yield event


def test_stream_project_chat_reply_yields_chunks_in_order(monkeypatch):
    fake = _FakeAgent(
        [
            {"event": "on_chain_start", "data": {}},
            {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("Hel")}},
            {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("lo")}},
            {"event": "on_chat_model_end", "data": {}},
        ]
    )
    monkeypatch.setattr(project_chat_agent, "_build_agent", lambda proj, p, m: fake)

    async def _collect():
        return [
            chunk
            async for chunk in project_chat_agent.stream_project_chat_reply(
                [{"role": "user", "content": "Hi"}],
                project="TestProject",
            )
        ]

    result = asyncio.run(_collect())

    assert result == [("content", "Hel"), ("content", "lo")]
    assert fake.received_input == {"messages": [{"role": "user", "content": "Hi"}]}


def test_stream_project_chat_reply_skips_chunks_with_empty_content(monkeypatch):
    fake = _FakeAgent(
        [
            {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("")}},
            {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("Hi")}},
        ]
    )
    monkeypatch.setattr(project_chat_agent, "_build_agent", lambda proj, p, m: fake)

    async def _collect():
        return [
            chunk
            async for chunk in project_chat_agent.stream_project_chat_reply(
                [{"role": "user", "content": "Hi"}],
                project="TestProject",
            )
        ]

    result = asyncio.run(_collect())
    assert result == [("content", "Hi")]


def test_stream_project_chat_reply_yields_reasoning_before_content(monkeypatch):
    fake = _FakeAgent(
        [
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": _FakeChunk("", reasoning="Denke nach...")},
            },
            {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("Antwort")}},
        ]
    )
    monkeypatch.setattr(project_chat_agent, "_build_agent", lambda proj, p, m: fake)

    async def _collect():
        return [
            item
            async for item in project_chat_agent.stream_project_chat_reply(
                [{"role": "user", "content": "Hi"}],
                project="TestProject",
            )
        ]

    result = asyncio.run(_collect())
    assert result == [("reasoning", "Denke nach..."), ("content", "Antwort")]


def test_stream_project_chat_reply_passes_project_provider_and_model(monkeypatch):
    captured = {}

    def _fake_build(project, provider, model):
        captured["project"] = project
        captured["provider"] = provider
        captured["model"] = model
        return _FakeAgent([])

    monkeypatch.setattr(project_chat_agent, "_build_agent", _fake_build)

    async def _collect():
        return [
            item
            async for item in project_chat_agent.stream_project_chat_reply(
                [{"role": "user", "content": "Hi"}],
                project="TestProject",
                provider="nvidia",
                model="meta/llama-3.3-70b-instruct",
            )
        ]

    asyncio.run(_collect())
    assert captured == {
        "project": "TestProject",
        "provider": "nvidia",
        "model": "meta/llama-3.3-70b-instruct",
    }
