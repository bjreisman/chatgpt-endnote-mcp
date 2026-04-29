"""Local chat app that combines EndNote tools with the OpenAI Responses API."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from endnote_mcp.tool_runtime import EndNoteToolRuntime

APP_INSTRUCTIONS = """
You are a research assistant with access to the user's local EndNote library.

Use the available tools proactively when the user asks about papers, citations,
topics, full text, bibliographies, or anything that likely depends on the
library contents. Prefer `search_library` first for broad discovery. Use
`search_fulltext` when the user asks for concepts, quotes, methods, or details
inside papers. Use `get_reference_details` before citing or summarizing a
specific paper if metadata is incomplete. Use `read_pdf_section` when you need
to inspect pages directly.

When you answer:
- Ground claims in the retrieved library results.
- Mention specific references by record number when helpful.
- Be honest about uncertainty or missing context.
- If the user's request is not about the library, answer normally without tools.
""".strip()


def build_tool_schemas() -> list[dict[str, Any]]:
    """Return the OpenAI function tool schemas exposed to the local chat app."""
    return [
        {
            "type": "function",
            "name": "search_library",
            "description": "Search the EndNote library across metadata, PDF full text, and semantic similarity.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in natural language."},
                    "year_from": {"type": ["string", "null"], "description": "Optional start year filter."},
                    "year_to": {"type": ["string", "null"], "description": "Optional end year filter."},
                    "author": {"type": ["string", "null"], "description": "Optional author name filter."},
                    "ref_type": {"type": ["string", "null"], "description": "Optional EndNote reference type filter."},
                    "limit": {"type": "integer", "description": "Maximum results to return."},
                },
                "required": ["query", "year_from", "year_to", "author", "ref_type", "limit"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "search_references",
            "description": "Search reference metadata like titles, authors, keywords, and abstracts.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "year_from": {"type": ["string", "null"]},
                    "year_to": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                    "ref_type": {"type": ["string", "null"]},
                    "limit": {"type": "integer"},
                },
                "required": ["query", "year_from", "year_to", "author", "ref_type", "limit"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "search_fulltext",
            "description": "Search within indexed PDF content to find concepts, methods, quotes, or passages.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query", "limit"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_reference_details",
            "description": "Fetch full metadata for a specific EndNote record number.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"rec_number": {"type": "integer"}},
                "required": ["rec_number"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "read_pdf_section",
            "description": "Read specific pages from a PDF attached to an EndNote reference.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rec_number": {"type": "integer"},
                    "start_page": {"type": "integer"},
                    "end_page": {"type": "integer"},
                },
                "required": ["rec_number", "start_page", "end_page"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_citation",
            "description": "Format a specific EndNote record into a citation in a chosen style.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rec_number": {"type": "integer"},
                    "style": {"type": "string"},
                },
                "required": ["rec_number", "style"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_bibliography",
            "description": "Generate a formatted bibliography for multiple EndNote record numbers.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rec_numbers": {"type": "string"},
                    "style": {"type": "string"},
                    "sort": {"type": "string"},
                },
                "required": ["rec_numbers", "style", "sort"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "find_related",
            "description": "Find references related to a given EndNote record.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rec_number": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["rec_number", "limit"],
                "additionalProperties": False,
            },
        },
    ]


def _response_text(response: Any) -> str:
    text = getattr(response, "output_text", "") or ""
    if text:
        return text
    output = getattr(response, "output", []) or []
    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", []) or []:
            if getattr(part, "type", None) == "output_text":
                return getattr(part, "text", "")
    return ""


@dataclass
class ChatSession:
    id: str
    previous_response_id: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


class InMemorySessionStore:
    """Simple in-memory session storage for local development."""

    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create(self, session_id: str | None) -> ChatSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        new_id = session_id or str(uuid.uuid4())
        session = ChatSession(id=new_id)
        self._sessions[new_id] = session
        return session


class LocalChatOrchestrator:
    """Run a user turn through the Responses API with local EndNote tools."""

    def __init__(
        self,
        runtime: EndNoteToolRuntime,
        client: OpenAI | Any,
        model: str,
        instructions: str = APP_INSTRUCTIONS,
        max_tool_rounds: int = 8,
    ):
        self.runtime = runtime
        self.client = client
        self.model = model
        self.instructions = instructions
        self.max_tool_rounds = max_tool_rounds
        self.tools = build_tool_schemas()

    def chat(self, session: ChatSession, user_message: str) -> dict[str, Any]:
        session.messages.append({"role": "user", "content": user_message})
        response = self.client.responses.create(
            model=self.model,
            instructions=self.instructions,
            previous_response_id=session.previous_response_id,
            input=[{"role": "user", "content": user_message}],
            tools=self.tools,
            parallel_tool_calls=False,
            store=False,
        )

        tool_trace: list[dict[str, Any]] = []

        for _ in range(self.max_tool_rounds):
            tool_calls = [item for item in (getattr(response, "output", []) or []) if getattr(item, "type", None) == "function_call"]
            if not tool_calls:
                answer = _response_text(response).strip()
                session.previous_response_id = getattr(response, "id", session.previous_response_id)
                session.messages.append({"role": "assistant", "content": answer})
                return {"answer": answer, "tool_trace": tool_trace, "response_id": session.previous_response_id}

            tool_outputs = []
            for tool_call in tool_calls:
                args = json.loads(getattr(tool_call, "arguments", "") or "{}")
                result = self.runtime.invoke_tool(tool_call.name, args)
                tool_trace.append({"name": tool_call.name, "arguments": args, "output": result})
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": result,
                    }
                )

            response = self.client.responses.create(
                model=self.model,
                instructions=self.instructions,
                previous_response_id=response.id,
                input=tool_outputs,
                tools=self.tools,
                parallel_tool_calls=False,
                store=False,
            )

        raise RuntimeError("Model exceeded maximum tool rounds without producing a final answer.")


def create_starlette_app(
    runtime: EndNoteToolRuntime | None = None,
    client: OpenAI | Any | None = None,
    model: str | None = None,
) -> Starlette:
    """Create the local chat web app."""
    runtime = runtime or EndNoteToolRuntime()
    client = client or OpenAI()
    model = model or os.environ.get("ENDNOTE_MCP_OPENAI_MODEL", "gpt-5-mini")
    sessions = InMemorySessionStore()
    orchestrator = LocalChatOrchestrator(runtime=runtime, client=client, model=model)

    async def homepage(_request):
        return HTMLResponse(_render_app_html(model=model))

    async def health(_request):
        return JSONResponse({"ok": True, "model": model})

    async def chat(request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON body."}, status_code=400)

        user_message = (payload.get("message") or "").strip()
        if not user_message:
            return JSONResponse({"ok": False, "error": "Message is required."}, status_code=400)

        session = sessions.get_or_create(payload.get("session_id"))
        try:
            result = orchestrator.chat(session, user_message)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc), "session_id": session.id}, status_code=500)

        return JSONResponse(
            {
                "ok": True,
                "session_id": session.id,
                "answer": result["answer"],
                "tool_trace": result["tool_trace"],
                "messages": session.messages,
                "model": model,
            }
        )

    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/api/health", health),
            Route("/api/chat", chat, methods=["POST"]),
        ]
    )
    app.state.sessions = sessions
    app.state.orchestrator = orchestrator
    return app


def _render_app_html(model: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>EndNote Local Chat</title>
    <style>
      :root {{
        --bg: #f4efe7;
        --panel: rgba(255,255,255,0.76);
        --ink: #1f2b24;
        --muted: #5f6f64;
        --accent: #155eef;
        --accent-2: #d96c3f;
        --border: rgba(31, 43, 36, 0.12);
        --shadow: 0 18px 60px rgba(43, 39, 28, 0.12);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(217,108,63,0.18), transparent 32%),
          radial-gradient(circle at right 20%, rgba(21,94,239,0.18), transparent 28%),
          linear-gradient(180deg, #f8f4ed 0%, var(--bg) 100%);
        font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
      }}
      .shell {{
        max-width: 1120px;
        margin: 0 auto;
        padding: 28px 18px 36px;
      }}
      .hero {{
        display: grid;
        grid-template-columns: 1.4fr 0.9fr;
        gap: 18px;
        margin-bottom: 18px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 26px;
        box-shadow: var(--shadow);
        backdrop-filter: blur(20px);
      }}
      .title {{
        padding: 28px;
      }}
      .eyebrow {{
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--accent);
      }}
      h1 {{
        margin: 10px 0 8px;
        font-size: clamp(2.2rem, 4vw, 4.3rem);
        line-height: 0.98;
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
        font-weight: 600;
      }}
      .subtitle {{
        max-width: 52ch;
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.55;
      }}
      .status {{
        padding: 24px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }}
      .status dl {{
        margin: 0;
        display: grid;
        gap: 14px;
      }}
      .status dt {{
        font-size: 0.74rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 4px;
      }}
      .status dd {{
        margin: 0;
        font-size: 1rem;
        font-weight: 600;
      }}
      .workspace {{
        display: grid;
        grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.8fr);
        gap: 18px;
      }}
      .chat {{
        padding: 22px;
      }}
      .messages {{
        min-height: 420px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        margin-bottom: 18px;
      }}
      .message {{
        padding: 16px 18px;
        border-radius: 18px;
        border: 1px solid var(--border);
        max-width: 88%;
        white-space: pre-wrap;
        line-height: 1.55;
      }}
      .message.user {{
        align-self: flex-end;
        background: linear-gradient(135deg, rgba(21,94,239,0.96), rgba(45,132,245,0.9));
        color: white;
        border-color: transparent;
      }}
      .message.assistant {{
        background: rgba(255,255,255,0.9);
      }}
      .composer {{
        border-top: 1px solid var(--border);
        padding-top: 16px;
      }}
      textarea {{
        width: 100%;
        min-height: 98px;
        resize: vertical;
        border-radius: 18px;
        border: 1px solid var(--border);
        padding: 16px;
        font: inherit;
        background: rgba(255,255,255,0.92);
        color: var(--ink);
      }}
      .actions {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: 12px;
        gap: 12px;
      }}
      .hint {{
        color: var(--muted);
        font-size: 0.92rem;
      }}
      button {{
        border: 0;
        border-radius: 999px;
        padding: 12px 18px;
        background: linear-gradient(135deg, var(--accent-2), var(--accent));
        color: white;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
        box-shadow: 0 12px 24px rgba(21,94,239,0.24);
      }}
      button:disabled {{
        opacity: 0.6;
        cursor: wait;
      }}
      .trace {{
        padding: 22px;
      }}
      .trace h2 {{
        margin: 0 0 12px;
        font-size: 1rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .trace-item {{
        padding: 14px 0;
        border-top: 1px solid var(--border);
      }}
      .trace-item:first-of-type {{ border-top: 0; }}
      .trace-name {{
        font-weight: 700;
        color: var(--accent);
        margin-bottom: 6px;
      }}
      code, pre {{
        font-family: "SFMono-Regular", "Consolas", "Liberation Mono", monospace;
        font-size: 0.88rem;
      }}
      pre {{
        margin: 8px 0 0;
        padding: 12px;
        border-radius: 12px;
        background: rgba(31,43,36,0.05);
        overflow-x: auto;
      }}
      @media (max-width: 900px) {{
        .hero, .workspace {{
          grid-template-columns: 1fr;
        }}
        .message {{ max-width: 100%; }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="hero">
        <div class="card title">
          <div class="eyebrow">Local Research Copilot</div>
          <h1>Ask your EndNote library like it already knows the paper you mean.</h1>
          <p class="subtitle">
            This local app keeps your EndNote index and PDF access on your machine, and uses the OpenAI API only for the conversational layer.
          </p>
        </div>
        <aside class="card status">
          <dl>
            <div>
              <dt>Default model</dt>
              <dd>{model}</dd>
            </div>
            <div>
              <dt>API key</dt>
              <dd id="apiStatus">Checking…</dd>
            </div>
            <div>
              <dt>Best prompts</dt>
              <dd>“Find papers on scenario planning in ports”</dd>
            </div>
          </dl>
        </aside>
      </section>

      <section class="workspace">
        <main class="card chat">
          <div class="messages" id="messages"></div>
          <div class="composer">
            <textarea id="prompt" placeholder="Ask about papers, citations, methods, or full text in your library…"></textarea>
            <div class="actions">
              <div class="hint" id="statusLine">Ready.</div>
              <button id="sendBtn">Ask Library</button>
            </div>
          </div>
        </main>

        <aside class="card trace">
          <h2>Tool Activity</h2>
          <div id="traceList" class="hint">No tool calls yet.</div>
        </aside>
      </section>
    </div>

    <script>
      let sessionId = null;
      const messagesEl = document.getElementById("messages");
      const traceEl = document.getElementById("traceList");
      const promptEl = document.getElementById("prompt");
      const sendBtn = document.getElementById("sendBtn");
      const statusEl = document.getElementById("statusLine");
      const apiStatusEl = document.getElementById("apiStatus");

      fetch("/api/health").then(r => r.json()).then(() => {{
        apiStatusEl.textContent = "Configured on server";
      }}).catch(() => {{
        apiStatusEl.textContent = "Unavailable";
      }});

      function addMessage(role, text) {{
        const node = document.createElement("div");
        node.className = `message ${{role}}`;
        node.textContent = text;
        messagesEl.appendChild(node);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }}

      function renderTrace(trace) {{
        if (!trace || !trace.length) {{
          traceEl.className = "hint";
          traceEl.textContent = "No tool calls for this turn.";
          return;
        }}
        traceEl.className = "";
        traceEl.innerHTML = "";
        trace.forEach(item => {{
          const row = document.createElement("div");
          row.className = "trace-item";
          row.innerHTML = `
            <div class="trace-name">${{item.name}}</div>
            <div class="hint">Arguments</div>
            <pre>${{JSON.stringify(item.arguments, null, 2)}}</pre>
          `;
          traceEl.appendChild(row);
        }});
      }}

      async function send() {{
        const message = promptEl.value.trim();
        if (!message) return;
        addMessage("user", message);
        promptEl.value = "";
        sendBtn.disabled = true;
        statusEl.textContent = "Thinking through your library…";
        renderTrace([]);

        try {{
          const res = await fetch("/api/chat", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ session_id: sessionId, message }})
          }});
          const data = await res.json();
          if (!data.ok) {{
            throw new Error(data.error || "Unknown server error");
          }}
          sessionId = data.session_id;
          addMessage("assistant", data.answer || "(No response text)");
          renderTrace(data.tool_trace || []);
          statusEl.textContent = "Ready for the next question.";
        }} catch (err) {{
          addMessage("assistant", `Error: ${{err.message}}`);
          statusEl.textContent = "Something went wrong.";
        }} finally {{
          sendBtn.disabled = false;
          promptEl.focus();
        }}
      }}

      sendBtn.addEventListener("click", send);
      promptEl.addEventListener("keydown", (event) => {{
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {{
          send();
        }}
      }});

      addMessage("assistant", "Ask me about your EndNote library. I can search references, inspect full text, and help cite what I find.");
    </script>
  </body>
</html>
"""

