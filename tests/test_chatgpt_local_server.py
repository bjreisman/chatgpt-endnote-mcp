"""Tests for the tunnel-backed local MCP server used with ChatGPT."""

import asyncio
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from endnote_mcp.chatgpt_local_server import (
    CHATGPT_LOCAL_TOOL_NAMES,
    build_chatgpt_local_mcp,
    create_chatgpt_local_app,
    resolve_chatgpt_local_settings,
)
from endnote_mcp.config import Config


def _write_config(path: Path, **overrides):
    raw = {
        "endnote_xml": str(path.parent / "library.xml"),
        "pdf_dir": str(path.parent),
        "db_path": str(path.parent / "library.db"),
        "max_pdf_pages": 30,
        "chatgpt_local_host": "127.0.0.1",
        "chatgpt_local_port": 8787,
        "chatgpt_local_token": "config-token",
    }
    raw.update(overrides)
    (path.parent / "library.xml").write_text("<xml><records /></xml>")
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def test_config_loads_chatgpt_local_fields(tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    cfg = Config.load(config_path)

    assert cfg.chatgpt_local_host == "127.0.0.1"
    assert cfg.chatgpt_local_port == 8787
    assert cfg.chatgpt_local_token == "config-token"
    assert cfg.chatgpt_local_url == "http://127.0.0.1:8787"


def test_resolve_chatgpt_local_settings_honors_env_overrides(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, chatgpt_local_host="127.0.0.1", chatgpt_local_port=8787, chatgpt_local_token="config-token")
    monkeypatch.setenv("ENDNOTE_MCP_CHATGPT_LOCAL_HOST", "0.0.0.0")
    monkeypatch.setenv("ENDNOTE_MCP_CHATGPT_LOCAL_PORT", "9797")
    monkeypatch.setenv("ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN", "env-token")

    host, port, token = resolve_chatgpt_local_settings(str(config_path))

    assert host == "0.0.0.0"
    assert port == 9797
    assert token == "env-token"


def test_resolve_chatgpt_local_settings_requires_token(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, chatgpt_local_token=None)
    monkeypatch.delenv("ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN", raising=False)

    with pytest.raises(ValueError, match="requires a bearer token"):
        resolve_chatgpt_local_settings(str(config_path))


def test_chatgpt_local_server_registers_only_read_fetch_tools():
    mcp = build_chatgpt_local_mcp()
    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert tool_names == set(CHATGPT_LOCAL_TOOL_NAMES)
    assert "rebuild_index" not in tool_names


def test_create_chatgpt_local_app_requires_token():
    with pytest.raises(ValueError, match="bearer token"):
        create_chatgpt_local_app(token=None)


def test_chatgpt_local_health_requires_auth_and_hides_paths():
    app = create_chatgpt_local_app(token="secret-token")
    client = TestClient(app)

    unauthorized = client.get("/health")
    assert unauthorized.status_code == 401

    authorized = client.get("/health", headers={"Authorization": "Bearer secret-token"})
    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["ok"] is True
    assert "db_path" not in payload
    assert "endnote_xml" not in payload


def test_chatgpt_local_app_mounts_streamable_http_server():
    app = create_chatgpt_local_app(token="secret-token")
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "" in paths
