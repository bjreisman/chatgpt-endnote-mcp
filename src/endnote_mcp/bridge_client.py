"""Client for forwarding tool calls to the local companion."""

from __future__ import annotations

import os
from urllib import error, request

from endnote_mcp.bridge_models import ToolInvokeRequest, ToolInvokeResponse
from endnote_mcp.config import Config


class BridgeClientError(RuntimeError):
    """Raised when the local companion cannot satisfy a request."""


class BridgeClient:
    """Forward tool invocations to a local HTTP companion."""

    def __init__(self, base_url: str, token: str | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def invoke(self, tool_name: str, arguments: dict | None = None) -> str:
        payload = ToolInvokeRequest(tool_name=tool_name, arguments=arguments or {})
        req = request.Request(
            f"{self.base_url}/invoke",
            method="POST",
            data=payload.to_json().encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise BridgeClientError(f"Companion request failed ({exc.code}): {message}") from exc
        except error.URLError as exc:
            raise BridgeClientError(f"Could not reach local companion at {self.base_url}: {exc.reason}") from exc

        result = ToolInvokeResponse.from_json(raw)
        if not result.ok:
            raise BridgeClientError(result.error_message or result.error_code or "Unknown bridge failure")
        return result.content


def make_bridge_client(config_path: str | None = None) -> BridgeClient:
    """Build a bridge client from config and environment."""
    cfg = Config.load(config_path)
    base_url = os.environ.get("ENDNOTE_MCP_COMPANION_URL", cfg.companion_url)
    token = os.environ.get("ENDNOTE_MCP_COMPANION_TOKEN", cfg.companion_token)
    timeout = int(os.environ.get("ENDNOTE_MCP_COMPANION_TIMEOUT", cfg.request_timeout_seconds))
    return BridgeClient(base_url=base_url, token=token, timeout=timeout)
