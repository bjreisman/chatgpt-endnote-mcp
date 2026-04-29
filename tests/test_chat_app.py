"""Tests for the local chat app orchestration."""

from types import SimpleNamespace

from endnote_mcp.chat_app import (
    ChatSession,
    InMemorySessionStore,
    LocalChatOrchestrator,
    build_tool_schemas,
    create_starlette_app,
)


class _FakeResponsesAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.responses = _FakeResponsesAPI(responses)


class _FakeRuntime:
    def __init__(self):
        self.calls = []

    def invoke_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return f"tool-result:{tool_name}:{arguments['query']}"


def test_build_tool_schemas_has_search_and_pdf_tools():
    tools = build_tool_schemas()
    names = {tool["name"] for tool in tools}
    assert "search_library" in names
    assert "search_fulltext" in names
    assert "read_pdf_section" in names


def test_session_store_reuses_existing_session():
    store = InMemorySessionStore()
    session = store.get_or_create(None)
    again = store.get_or_create(session.id)
    assert again is session


def test_orchestrator_runs_tool_loop_then_returns_answer():
    tool_call = SimpleNamespace(
        type="function_call",
        name="search_library",
        arguments='{"query":"ports"}',
        call_id="call_1",
    )
    first_response = SimpleNamespace(id="resp_1", output=[tool_call], output_text="")
    final_response = SimpleNamespace(id="resp_2", output=[], output_text="Found two relevant papers.")

    runtime = _FakeRuntime()
    client = _FakeClient([first_response, final_response])
    orchestrator = LocalChatOrchestrator(runtime=runtime, client=client, model="gpt-5-mini")
    session = ChatSession(id="abc")

    result = orchestrator.chat(session, "Find port planning papers")

    assert result["answer"] == "Found two relevant papers."
    assert runtime.calls == [("search_library", {"query": "ports"})]
    assert session.previous_response_id == "resp_2"
    assert session.messages[-1]["role"] == "assistant"
    assert len(client.responses.calls) == 2


def test_create_starlette_app_exposes_routes():
    app = create_starlette_app(runtime=_FakeRuntime(), client=_FakeClient([]), model="gpt-5-mini")
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/api/health" in paths
    assert "/api/chat" in paths
