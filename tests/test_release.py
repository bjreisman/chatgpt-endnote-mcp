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
    assert "experimental" not in project["project"]["optional-dependencies"]
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/endnote_mcp"]


def test_plugin_launches_stdio_server_without_download_on_startup():
    plugin = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    assert plugin["version"] == tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    mcp = json.loads((ROOT / plugin["mcpServers"]).read_text())
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


def test_copied_plugin_launches_real_stdio_server(tmp_path):
    import asyncio
    import os
    import shlex
    import shutil
    import sys
    from click.testing import CliRunner
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from endnote_mcp.desktop_cli import cli

    # Exercise a plugin copy outside the source root, as in a local plugin cache.
    plugin_root = tmp_path / "installed plugin"
    for directory in (".codex-plugin", "scripts", "skills"):
        shutil.copytree(ROOT / directory, plugin_root / directory)
    shutil.copy2(ROOT / ".mcp.json", plugin_root / ".mcp.json")
    manifest = json.loads((plugin_root / ".codex-plugin/plugin.json").read_text())
    mcp = json.loads((plugin_root / manifest["mcpServers"]).read_text())
    server = mcp["mcpServers"]["endnote"]
    assert (plugin_root / manifest["skills"] / "endnote-research/SKILL.md").is_file()
    pdfs = tmp_path / "PDF"
    pdfs.mkdir()
    config = tmp_path / "fixture/config.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["setup", "--xml", str(ROOT / "examples/library.xml"),
                                "--pdf-dir", str(pdfs), "--config", str(config)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["index", "--config", str(config), "--skip-pdfs"])
    assert result.exit_code == 0, result.output
    executable = tmp_path / "local desktop command"
    executable.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable)
                          + ' -m endnote_mcp.desktop_cli "$@"\n')
    executable.chmod(0o755)

    async def run():
        params = StdioServerParameters(command=server["command"], args=server["args"],
            cwd=str(plugin_root / server["cwd"]), env={**os.environ,
                "CHATGPT_ENDNOTE_MCP_COMMAND": str(executable),
                "CHATGPT_ENDNOTE_MCP_CONFIG": str(config)})
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), 30)
                assert len((await session.list_tools()).tools) == 11
                result = await session.call_tool("search_references", {"query": "EXAMPLE"})
                assert not result.isError
                assert result.structuredContent["items"]

    asyncio.run(run())
