"""Local companion HTTP service for ChatGPT bridge development."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from endnote_mcp.bridge_models import ToolInvokeRequest, ToolInvokeResponse
from endnote_mcp.tool_runtime import EndNoteToolRuntime


class CompanionService:
    """HTTP wrapper around the shared EndNote tool runtime."""

    def __init__(self, runtime: EndNoteToolRuntime, token: str | None = None):
        self.runtime = runtime
        self.token = token

    def health_payload(self) -> dict:
        cfg = self.runtime._get_config()
        return {
            "ok": True,
            "db_path": str(cfg.db_path),
            "endnote_xml": str(cfg.endnote_xml),
        }

    def invoke(self, req: ToolInvokeRequest) -> ToolInvokeResponse:
        try:
            content = self.runtime.invoke_tool(req.tool_name, req.arguments)
        except Exception as exc:
            return ToolInvokeResponse(
                ok=False,
                error_code="tool_error",
                error_message=str(exc),
                request_id=req.request_id,
            )
        return ToolInvokeResponse(ok=True, content=content, request_id=req.request_id)


def make_handler(service: CompanionService):
    """Create a request handler bound to a companion service."""

    class CompanionHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self._write_json(200, service.health_payload())

        def do_POST(self):
            if self.path != "/invoke":
                self.send_error(404)
                return
            if service.token:
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {service.token}":
                    self._write_json(401, {"ok": False, "error": "unauthorized"})
                    return

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                req = ToolInvokeRequest.from_json(raw)
            except Exception:
                self._write_json(400, {"ok": False, "error": "invalid_request"})
                return

            resp = service.invoke(req)
            code = 200 if resp.ok else 500
            self._write_json(code, json.loads(resp.to_json()))

        def log_message(self, format, *args):
            return

        def _write_json(self, code: int, payload: dict):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return CompanionHandler


def serve_companion(
    host: str,
    port: int,
    runtime: EndNoteToolRuntime,
    token: str | None = None,
) -> None:
    """Serve the local companion until interrupted."""
    service = CompanionService(runtime=runtime, token=token)
    server = ThreadingHTTPServer((host, port), make_handler(service))
    try:
        server.serve_forever()
    finally:
        server.server_close()
