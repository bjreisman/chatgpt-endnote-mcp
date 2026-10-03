"""Native launcher/install checks and platform ZIP contracts."""
import asyncio
from contextlib import closing
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest
from click.testing import CliRunner

ROOT = Path(__file__).parents[1]
WINDOWS = pytest.mark.skipif(os.name != 'nt', reason='Native Windows integration')


def plugin_build():
    spec = importlib.util.spec_from_file_location('build_plugin', ROOT / 'scripts/build_plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build


def package(tmp_path, platform):
    # A synthetic sdist with the real runtime/resources, excluding private data.
    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as target:
        for name in ('src', 'scripts', 'skills', 'assets', '.codex-plugin', '.claude-plugin', '.mcp.json', 'pyproject.toml', 'README.md', 'LICENSE'):
            target.add(ROOT / name, arcname='package/' + name)
    output = tmp_path / (platform + '.zip')
    plugin_build()(archive, output, platform)
    return output


@pytest.mark.parametrize('platform,command', [('unix', 'sh'), ('windows', 'cmd.exe')])
def test_platform_packages(tmp_path, platform, command):
    archive = package(tmp_path, platform)
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read('.mcp.json'))
        assert manifest['mcpServers']['endnote']['command'] == command
        assert 'CHATGPT_ENDNOTE_MCP_COMMAND' in manifest['mcpServers']['endnote']['env_vars']
        assert 'CHATGPT_ENDNOTE_MCP_CONFIG' in manifest['mcpServers']['endnote']['env_vars']
        if platform == 'windows':
            assert manifest['mcpServers']['endnote']['startup_timeout_sec'] == 60
        assert 'src/endnote_mcp/pdf_worker.py' in source.namelist()
        assert 'scripts/install-desktop.ps1' in source.namelist()
        assert 'scripts/launch-desktop.cmd' in source.namelist()
        assert not any(n.endswith(('.db', 'config.yaml')) for n in source.namelist())
    assert json.loads((ROOT / '.mcp.json').read_text())['mcpServers']['endnote']['command'] == 'sh'


def test_unix_package_normalizes_windows_shell_line_endings(tmp_path):
    archive = tmp_path / 'crlf-source.tar.gz'
    script = b'#!/bin/sh\r\nset -eu\r\nprintf "ok\\n"\r\n'
    with tarfile.open(archive, 'w:gz') as source:
        member = tarfile.TarInfo('package/scripts/launch-desktop.sh')
        member.size = len(script)
        member.mode = 0o755
        source.addfile(member, io.BytesIO(script))
    output = tmp_path / 'unix.zip'
    plugin_build()(archive, output)
    with zipfile.ZipFile(output) as package:
        assert package.read('scripts/launch-desktop.sh') == script.replace(b'\r\n', b'\n')
        assert (package.getinfo('scripts/launch-desktop.sh').external_attr >> 16) & 0o111


def native_stub(tmp_path, name, body):
    """Build an actual .exe console entry point, without depending on a shell."""
    from distlib.scripts import ScriptMaker
    module_name = name.replace('-', '_') + '_module'
    module = tmp_path / (module_name + '.py')
    module.write_text('def main():\n' + '\n'.join('    ' + line for line in body.splitlines()) + '\n', encoding='utf-8')
    maker = ScriptMaker(None, str(tmp_path))
    maker.executable = sys.executable
    maker.variants = {''}
    maker.make(f'{name} = {module_name}:main')
    return tmp_path / (name + '.exe')


@WINDOWS
def test_launcher_preserves_bytes_arguments_and_exit_code(tmp_path):
    directory = tmp_path / "spaced Ω & dollar$ bang! quote'"
    directory.mkdir()
    executable = native_stub(directory, 'runtime', """import json, sys
sys.stdout.buffer.write(json.dumps(sys.argv[1:], ensure_ascii=False).encode('utf-8'))
sys.stderr.buffer.write('diagnostic Ω'.encode('utf-8'))
raise SystemExit(23)""")
    config = str(directory / 'config.yaml')
    env = {**os.environ, 'CHATGPT_ENDNOTE_MCP_COMMAND': str(executable), 'PYTHONPATH': str(directory)}
    # Match CreateProcess invocation by the MCP client; arguments are quoted.
    command = f'cmd.exe /d /c ""{ROOT / "scripts/launch-desktop.cmd"}" --config "{config}""'
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 23, result.stderr
    assert json.loads(result.stdout.decode('utf-8')) == ['serve-desktop', '--config', config]
    assert result.stderr.decode('utf-8') == 'diagnostic Ω'


@WINDOWS
def test_launcher_missing_override_and_missing_runtime(tmp_path):
    env = {**os.environ, 'CHATGPT_ENDNOTE_MCP_COMMAND': str(tmp_path / 'absent.exe')}
    command = f'cmd.exe /d /c ""{ROOT / "scripts/launch-desktop.cmd"}""'
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 127
    assert not result.stdout
    env.pop('CHATGPT_ENDNOTE_MCP_COMMAND')
    for name in ('PATH', 'UV_TOOL_BIN_DIR', 'XDG_BIN_HOME', 'XDG_DATA_HOME'):
        env.pop(name, None)
    env['USERPROFILE'] = str(tmp_path)
    command = command.replace('cmd.exe', str(Path(os.environ['SystemRoot']) / 'System32/cmd.exe'), 1)
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 127
    assert not result.stdout


@WINDOWS
@pytest.mark.parametrize('location', ['PATH', 'UV_TOOL_BIN_DIR', 'XDG_BIN_HOME', 'XDG_DATA_HOME', 'USERPROFILE'])
def test_launcher_discovery(tmp_path, location):
    directory = tmp_path / 'bin with spaces Ω'
    directory.mkdir()
    native_stub(directory, 'chatgpt-endnote-mcp', 'import sys\nsys.stdout.buffer.write(b"native")')
    env = {**os.environ, 'PYTHONPATH': str(directory)}
    for name in ('CHATGPT_ENDNOTE_MCP_COMMAND', 'PATH', 'UV_TOOL_BIN_DIR', 'XDG_BIN_HOME', 'XDG_DATA_HOME'):
        env.pop(name, None)
    env['USERPROFILE'] = str(tmp_path / 'empty')
    if location == 'XDG_DATA_HOME':
        env[location] = str(directory.parent / 'data')
        Path(env[location]).mkdir()
        # XDG_DATA_HOME/../bin is the documented fallback.
        shutil.copytree(directory, tmp_path / 'bin')
    elif location == 'USERPROFILE':
        env[location] = str(tmp_path / 'profile')
        shutil.copytree(directory, Path(env[location]) / '.local/bin')
    else:
        env[location] = str(directory)
    command = f'"{Path(os.environ["SystemRoot"]) / "System32/cmd.exe"}" /d /c ""{ROOT / "scripts/launch-desktop.cmd"}""'
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b'native'


@WINDOWS
def test_native_installer_flags_failure_and_missing_uv(tmp_path):
    directory = tmp_path / 'native tools Ω'
    directory.mkdir()
    runtime = native_stub(directory, 'chatgpt-endnote-mcp', 'print("test runtime")')
    uv = native_stub(directory, 'uv', """import json, os, pathlib, sys
if sys.argv[1:] == ['tool', 'dir', '--bin']:
    print(os.environ['TEST_BIN'])
else:
    pathlib.Path(os.environ['TEST_LOG']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')
raise SystemExit(int(os.environ.get('TEST_EXIT', '0')))""")
    plugin = tmp_path / 'plugin with spaces Ω'
    (plugin / 'scripts').mkdir(parents=True)
    script = plugin / 'scripts/install-desktop.ps1'
    shutil.copy2(ROOT / 'scripts/install-desktop.ps1', script)
    log = tmp_path / 'log.json'
    env = {**os.environ, 'PYTHONPATH': str(directory), 'PYTHONIOENCODING': 'utf-8', 'CHATGPT_ENDNOTE_MCP_UV': str(uv), 'TEST_BIN': str(directory), 'TEST_LOG': str(log)}
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text(encoding='utf-8')) == ['tool', 'install', str(plugin)]
    result = subprocess.run([*command, '-Semantic', '-Replace'], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text(encoding='utf-8')) == ['tool', 'install', '--force', str(plugin) + '[semantic]']
    env['TEST_EXIT'] = '19'
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 19
    assert b'Runtime executable:' not in result.stdout
    env['CHATGPT_ENDNOTE_MCP_UV'] = str(tmp_path / 'missing.exe')
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 127
    assert b'uv executable is unavailable' in result.stderr
    env.pop('CHATGPT_ENDNOTE_MCP_UV')
    env.pop('TEST_EXIT')
    second_uv = tmp_path / 'second uv'
    second_uv.mkdir()
    native_stub(second_uv, 'uv', 'raise SystemExit(88)')
    env['PATH'] = str(directory) + os.pathsep + str(second_uv) + os.pathsep + os.environ['PATH']
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    profile = tmp_path / 'isolated profile'
    shutil.copytree(directory, profile / '.local/bin')
    powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    command[0] = powershell
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    env['USERPROFILE'] = str(profile)
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    env['USERPROFILE'] = str(tmp_path / 'absent profile')
    result = subprocess.run(command, env=env, capture_output=True)
    assert result.returncode == 127
    assert b'uv is required' in result.stderr


@pytest.mark.parametrize('platform', ['unix', 'windows'])
def test_platform_zip_real_stdio_and_incremental_update(tmp_path, platform):
    if (platform == 'windows') != (os.name == 'nt'):
        pytest.skip('Run the package on its native platform')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from endnote_mcp.desktop_cli import cli
    from endnote_mcp import db
    import pymupdf

    plugin = tmp_path / "installed plugin Ω & bang!"
    plugin.mkdir()
    with zipfile.ZipFile(package(tmp_path, platform)) as source:
        source.extractall(plugin)
    data = tmp_path / "library Ω & dollar$ bang! quote'"
    pdfs = data / 'PDF/nested'
    pdfs.mkdir(parents=True)
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), 'Published synthetic evidence')
        doc.save(pdfs / 'paper.pdf')
    xml = data / 'export.xml'
    def export(title):
        xml.write_text(f'<xml><records><record><rec-number>1</rec-number><titles><title>{title}</title></titles><urls><pdf-urls><url>internal-pdf://nested/paper.pdf</url></pdf-urls></urls></record></records></xml>', encoding='utf-8')
    export('Synthetic Ω reference')
    config = data / 'config.yaml'
    runner = CliRunner()
    for arguments in (['setup', '--xml', str(xml), '--pdf-dir', str(pdfs.parent), '--config', str(config)], ['index', '--config', str(config)]):
        result = runner.invoke(cli, arguments)
        assert result.exit_code == 0, result.output
    executable = Path(sys.executable).parent / ('chatgpt-endnote-mcp.exe' if os.name == 'nt' else 'chatgpt-endnote-mcp')
    assert executable.is_file()
    server = json.loads((plugin / '.mcp.json').read_text())['mcpServers']['endnote']
    params = StdioServerParameters(command=server['command'], args=server['args'], cwd=str(plugin), env={**os.environ, 'CHATGPT_ENDNOTE_MCP_COMMAND': str(executable), 'CHATGPT_ENDNOTE_MCP_CONFIG': str(config)})
    database = data / 'library.db'
    async def run():
        for restart in range(2):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await asyncio.wait_for(session.initialize(), 30)
                    assert len((await session.list_tools()).tools) == 11
                    before = database.read_bytes()
                    for name, arguments in [('search_references', {'query': 'Updated' if restart else 'Synthetic'}), ('search_fulltext', {'query': 'evidence'}), ('get_citation', {'rec_number': 1}), ('read_pdf_section', {'rec_number': 1})]:
                        response = await session.call_tool(name, arguments)
                        assert not response.isError
                        assert response.structuredContent['items']
                    assert database.read_bytes() == before
                    response = await session.call_tool('search_semantic', {'query': 'energy'})
                    assert response.structuredContent['error']['code'] == 'semantic_unavailable'
                    if restart == 0:
                        export('Updated Ω reference')
                        result = await asyncio.to_thread(runner.invoke, cli, ['index', '--config', str(config)])
                        assert result.exit_code == 0, result.output
                        response = await session.call_tool('search_references', {'query': 'Updated'})
                        assert response.structuredContent['items'][0]['title'] == 'Updated Ω reference'
    asyncio.run(run())
    with closing(db.connect_readonly(database)) as connection:
        assert db.get_stats(connection)['total_pdf_pages'] == 1
