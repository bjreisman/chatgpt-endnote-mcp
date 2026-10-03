import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).parents[1]


def test_package_installs_the_local_desktop_command_without_experimental_http_deps():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["name"] == "chatgpt-endnote-mcp"
    assert project["project"]["scripts"]["chatgpt-endnote-mcp"] == "endnote_mcp.desktop_cli:main"
    assert "openai" not in project["project"]["dependencies"]
    assert "uvicorn" not in project["project"]["dependencies"]
    assert "openai>=2.0.0" in project["project"]["optional-dependencies"]["experimental"]
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/endnote_mcp"]


def test_plugin_launches_stdio_server_without_download_on_startup():
    plugin = json.loads((ROOT / "plugin.json").read_text())
    assert plugin["version"] == "1.4.5"
    mcp = json.loads((ROOT / "mcp.json").read_text())
    server = mcp["mcpServers"]["endnote"]
    assert server["command"] == "sh"
    args = server["args"]
    assert args[0] == "./scripts/launch-desktop.sh"
    assert all("uvx" not in arg for arg in args)
    launcher = (ROOT / "scripts/launch-desktop.sh").read_text()
    assert "exec \"$executable\" serve-desktop \"$@\"" in launcher
    assert "CHATGPT_ENDNOTE_MCP_COMMAND" in launcher


def test_examples_are_marked_fabricated():
    xml = (ROOT / "examples/library.xml").read_text()
    from endnote_mcp.endnote_parser import parse_endnote_xml

    parsed = list(parse_endnote_xml(ROOT / "examples/library.xml"))
    assert len(parsed) == 2
    assert [reference["rec_number"] for reference in parsed] == [900001, 900002]
    assert "EXAMPLE-001" in xml and "EXAMPLE-002" in xml
    assert "Fabricated fixture" in xml


def test_launcher_executes_override_and_preserves_arguments_with_spaces(tmp_path):
    import os
    import subprocess

    executable = tmp_path / "fake executable"
    capture = tmp_path / "captured arguments"
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
    executable.chmod(0o755)
    config = tmp_path / "path with spaces" / "config.yaml"
    env = os.environ.copy()
    env.update({"CHATGPT_ENDNOTE_MCP_COMMAND": str(executable), "CAPTURE": str(capture)})
    subprocess.run(["sh", str(ROOT / "scripts/launch-desktop.sh"), "--config", str(config)], env=env, check=True)
    assert capture.read_text().splitlines() == ["serve-desktop", "--config", str(config)]
