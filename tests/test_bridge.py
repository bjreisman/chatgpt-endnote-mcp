"""Tests for bridge request/response handling and local companion forwarding."""

import json
import threading
import time
import urllib.request
from pathlib import Path

import yaml

from endnote_mcp.bridge_client import BridgeClient, BridgeClientError
from endnote_mcp.bridge_models import ToolInvokeRequest, ToolInvokeResponse
from endnote_mcp.companion import serve_companion
from endnote_mcp.db import connect, insert_pdf_page, upsert_reference
from endnote_mcp.tool_runtime import EndNoteToolRuntime


def _write_config(config_path: Path, db_path: Path):
    config_path.write_text(
        yaml.safe_dump(
            {
                "endnote_xml": str(config_path.parent / "library.xml"),
                "pdf_dir": str(config_path.parent),
                "db_path": str(db_path),
                "max_pdf_pages": 30,
                "companion_host": "127.0.0.1",
                "companion_port": 8876,
                "companion_token": "secret-token",
                "request_timeout_seconds": 5,
            },
            sort_keys=False,
        )
    )


def _seed_db(db_path: Path):
    conn = connect(db_path)
    upsert_reference(
        conn,
        {
            "rec_number": 7,
            "ref_type": "Journal Article",
            "title": "Harbor Logistics and Reliability",
            "authors": json.dumps(["Smith, J."]),
            "year": "2024",
            "journal": "Port Studies",
            "volume": "9",
            "issue": "1",
            "pages": "1-15",
            "abstract": "Research on port reliability.",
            "keywords": json.dumps(["shipping", "reliability"]),
            "doi": "10.1000/port.2024",
            "url": "",
            "publisher": "",
            "place_published": "",
            "edition": "",
            "isbn": "",
            "label": "",
            "notes": "",
            "pdf_path": "",
        },
    )
    insert_pdf_page(conn, 7, 1, "Shipping reliability depends on port coordination.")
    conn.commit()
    conn.close()


def test_tool_invoke_request_roundtrip():
    req = ToolInvokeRequest(tool_name="search_references", arguments={"query": "shipping"}, request_id="abc")
    restored = ToolInvokeRequest.from_json(req.to_json())
    assert restored.tool_name == "search_references"
    assert restored.arguments == {"query": "shipping"}
    assert restored.request_id == "abc"


def test_tool_invoke_response_roundtrip():
    resp = ToolInvokeResponse(ok=True, content="hi", request_id="abc", metadata={"source": "companion"})
    restored = ToolInvokeResponse.from_json(resp.to_json())
    assert restored.ok is True
    assert restored.content == "hi"
    assert restored.metadata == {"source": "companion"}


def test_companion_bridge_roundtrip(tmp_path):
    db_path = tmp_path / "library.db"
    config_path = tmp_path / "config.yaml"
    xml_path = tmp_path / "library.xml"
    xml_path.write_text("<xml><records /></xml>")
    _seed_db(db_path)
    _write_config(config_path, db_path)

    runtime = EndNoteToolRuntime(config_path=config_path)
    thread = threading.Thread(
        target=serve_companion,
        kwargs={"host": "127.0.0.1", "port": 8876, "runtime": runtime, "token": "secret-token"},
        daemon=True,
    )
    thread.start()
    time.sleep(0.2)

    client = BridgeClient(base_url="http://127.0.0.1:8876", token="secret-token", timeout=5)
    result = client.invoke("search_references", {"query": "shipping"})
    assert "Harbor Logistics and Reliability" in result

    with urllib.request.urlopen("http://127.0.0.1:8876/health", timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload["ok"] is True


def test_companion_rejects_missing_token(tmp_path):
    db_path = tmp_path / "library.db"
    config_path = tmp_path / "config.yaml"
    xml_path = tmp_path / "library.xml"
    xml_path.write_text("<xml><records /></xml>")
    _seed_db(db_path)
    _write_config(config_path, db_path)

    runtime = EndNoteToolRuntime(config_path=config_path)
    thread = threading.Thread(
        target=serve_companion,
        kwargs={"host": "127.0.0.1", "port": 8877, "runtime": runtime, "token": "secret-token"},
        daemon=True,
    )
    thread.start()
    time.sleep(0.2)

    client = BridgeClient(base_url="http://127.0.0.1:8877", token=None, timeout=5)
    try:
        client.invoke("search_references", {"query": "shipping"})
    except BridgeClientError as exc:
        assert "401" in str(exc)
    else:
        raise AssertionError("Expected unauthorized bridge failure")
