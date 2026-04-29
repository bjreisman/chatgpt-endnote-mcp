"""Tunnel-backed local MCP server for ChatGPT dev/demo use."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from endnote_mcp.config import Config
from endnote_mcp.tool_runtime import EndNoteToolRuntime

CHATGPT_LOCAL_TOOL_NAMES = [
    "search_references",
    "search_fulltext",
    "search_library",
    "search_semantic",
    "get_reference_details",
    "get_citation",
    "get_bibtex",
    "get_bibliography",
    "find_related",
    "read_pdf_section",
    "list_references_by_topic",
]


def resolve_chatgpt_local_settings(config_path: str | None = None) -> tuple[str, int, str]:
    """Resolve host, port, and token for the ChatGPT-local server."""
    cfg = Config.load(config_path)
    host = os.environ.get("ENDNOTE_MCP_CHATGPT_LOCAL_HOST", cfg.chatgpt_local_host)
    port = int(os.environ.get("ENDNOTE_MCP_CHATGPT_LOCAL_PORT", cfg.chatgpt_local_port))
    token = os.environ.get("ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN", cfg.chatgpt_local_token)
    if not token:
        raise ValueError(
            "ChatGPT-local MCP mode requires a bearer token. "
            "Set ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN or chatgpt_local_token in config."
        )
    return host, port, token


def build_chatgpt_local_mcp(runtime: EndNoteToolRuntime | None = None) -> FastMCP:
    """Build a dedicated read/fetch-only MCP server for ChatGPT tunnel use."""
    runtime = runtime or EndNoteToolRuntime()
    mcp = FastMCP(
        "EndNote Library (ChatGPT Local)",
        instructions=(
            "Read-only EndNote library access for ChatGPT development via a tunnel-backed "
            "local MCP server. Search references, inspect metadata, read indexed PDF content, "
            "and format citations."
        ),
    )

    @mcp.tool()
    def search_references(
        query: str,
        year_from: str | None = None,
        year_to: str | None = None,
        author: str | None = None,
        ref_type: str | None = None,
        limit: int = 50,
    ) -> str:
        return runtime.search_references(
            query=query,
            year_from=year_from,
            year_to=year_to,
            author=author,
            ref_type=ref_type,
            limit=limit,
        )

    @mcp.tool()
    def search_fulltext(query: str, limit: int = 50) -> str:
        return runtime.search_fulltext(query=query, limit=limit)

    @mcp.tool()
    def search_library(
        query: str,
        year_from: str | None = None,
        year_to: str | None = None,
        author: str | None = None,
        ref_type: str | None = None,
        limit: int = 30,
    ) -> str:
        return runtime.search_library(
            query=query,
            year_from=year_from,
            year_to=year_to,
            author=author,
            ref_type=ref_type,
            limit=limit,
        )

    @mcp.tool()
    def search_semantic(query: str, limit: int = 20) -> str:
        return runtime.search_semantic(query=query, limit=limit)

    @mcp.tool()
    def get_reference_details(rec_number: int) -> str:
        return runtime.get_reference_details(rec_number=rec_number)

    @mcp.tool()
    def get_citation(rec_number: int, style: str = "apa7") -> str:
        return runtime.get_citation(rec_number=rec_number, style=style)

    @mcp.tool()
    def get_bibtex(rec_numbers: str) -> str:
        return runtime.get_bibtex(rec_numbers=rec_numbers)

    @mcp.tool()
    def get_bibliography(rec_numbers: str, style: str = "apa7", sort: str = "author") -> str:
        return runtime.get_bibliography(rec_numbers=rec_numbers, style=style, sort=sort)

    @mcp.tool()
    def find_related(rec_number: int, limit: int = 10) -> str:
        return runtime.find_related(rec_number=rec_number, limit=limit)

    @mcp.tool()
    def read_pdf_section(rec_number: int, start_page: int = 1, end_page: int = 5) -> str:
        return runtime.read_pdf_section(rec_number=rec_number, start_page=start_page, end_page=end_page)

    @mcp.tool()
    def list_references_by_topic(
        topic: str,
        year_from: str | None = None,
        year_to: str | None = None,
        ref_type: str | None = None,
        limit: int = 50,
    ) -> str:
        return runtime.list_references_by_topic(
            topic=topic,
            year_from=year_from,
            year_to=year_to,
            ref_type=ref_type,
            limit=limit,
        )

    return mcp


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests that do not present the expected bearer token."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path == "/health":
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {self.token}":
                return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        else:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {self.token}":
                return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        return await call_next(request)


def create_chatgpt_local_app(runtime: EndNoteToolRuntime | None = None, token: str | None = None) -> Starlette:
    """Create the Starlette app used for the local ChatGPT tunnel workflow."""
    if not token:
        raise ValueError("A bearer token is required for the ChatGPT-local MCP server.")

    mcp = build_chatgpt_local_mcp(runtime=runtime)
    mcp_app = mcp.streamable_http_app()

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "endnote-chatgpt-local", "mode": "dev-demo"})

    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=mcp_app),
        ]
    )
    app.add_middleware(BearerTokenMiddleware, token=token)
    app.state.mcp = mcp
    return app
