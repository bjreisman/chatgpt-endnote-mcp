"""Desktop adapter surface and actual stdio lifecycle checks."""
import asyncio
import json
import subprocess
import sys

import pytest

from endnote_mcp.desktop_server import build_desktop_mcp

TOOLS = {
    'search_references', 'search_fulltext', 'search_library', 'get_reference_details',
    'get_citation', 'read_pdf_section', 'list_references_by_topic', 'find_related',
    'get_bibliography', 'search_semantic', 'get_bibtex',
}


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name not in TOOLS:
            raise AttributeError(name)
        def call(**kwargs):
            self.calls.append((name, kwargs))
            return {'text': 'Synthetic evidence', 'items': [{'rec_number': 42}],
                    'pagination': {'has_more': False}, 'tool': name}
        return call


def test_readonly_surface_and_search_schemas():
    server = build_desktop_mcp(FakeRuntime())
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == TOOLS
    for tool in tools:
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False
        assert tool.outputSchema is not None
        if tool.name.startswith('search_'):
            props = tool.inputSchema['properties']
            assert props['limit']['default'] == 20
            assert props['offset']['default'] == 0
            assert {'author', 'year_from', 'year_to', 'ref_type'} <= props.keys()
    pdf = next(tool for tool in tools if tool.name == 'read_pdf_section')
    assert 'attachment_id' in pdf.inputSchema['properties']


@pytest.mark.parametrize('name,args', [
    ('search_references', {'query': 'AOX', 'author': 'Smith', 'offset': 20}),
    ('search_fulltext', {'query': 'BAX', 'year_from': '2000'}),
    ('search_library', {'query': 'fusion', 'ref_type': 'Journal Article'}),
    ('search_semantic', {'query': 'electron transport', 'year_to': '2025'}),
    ('get_reference_details', {'rec_number': 42}),
    ('get_citation', {'rec_number': 42, 'style': 'apa7'}),
    ('read_pdf_section', {'rec_number': 42, 'attachment_id': '42:1', 'end_page': 30}),
    ('list_references_by_topic', {'topic': 'mitochondria', 'offset': 20}),
    ('find_related', {'rec_number': 42, 'offset': 20}),
    ('get_bibliography', {'rec_numbers': '42,43'}),
    ('get_bibtex', {'rec_numbers': '42,43'}),
])
def test_tool_dispatch_and_structured_output(name, args):
    runtime = FakeRuntime()
    result = asyncio.run(build_desktop_mcp(runtime).call_tool(name, args))
    # SDK supplies readable JSON text and structuredContent for typed dict results.
    if isinstance(result, tuple):
        blocks, structured = result
        assert structured['tool'] == name
        assert json.loads(blocks[0].text)['items'][0]['rec_number'] == 42
    else:
        assert result['tool'] == name
    assert runtime.calls[0][0] == name
    assert all(runtime.calls[0][1][key] == value for key, value in args.items())


def test_actual_stdio_initialization_call_shutdown_and_restart(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    runner = tmp_path / 'fake_server.py'
    runner.write_text('''from endnote_mcp.desktop_server import build_desktop_mcp
class Runtime:
    def get_reference_details(self, **kwargs):
        return {"text": "Synthetic reference", "items": [kwargs]}
build_desktop_mcp(Runtime()).run(transport="stdio")
''')

    async def cycle():
        params = StdioServerParameters(command=sys.executable, args=[str(runner)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await asyncio.wait_for(session.initialize(), timeout=30)
                assert initialized.serverInfo.name == 'chatgpt-endnote-mcp'
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == TOOLS
                result = await session.call_tool('get_reference_details', {'rec_number': 42})
                assert not result.isError
                assert result.structuredContent['items'] == [{'rec_number': 42}]

    asyncio.run(cycle())
    asyncio.run(cycle())


def test_main_failure_is_stderr_only_and_missing_index_not_created(tmp_path):
    # Use the production entry point and an explicit isolated configuration.
    config = tmp_path / 'config.yaml'
    missing = tmp_path / 'missing.db'
    config.write_text(f'endnote_xml: {tmp_path / "library.xml"}\npdf_dir: {tmp_path}\ndb_path: {missing}\n')
    runner = 'from endnote_mcp.desktop_server import main; import sys; main(sys.argv[1])'
    result = subprocess.run([sys.executable, '-c', runner, str(config)],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'index' in result.stderr.lower()
    assert not missing.exists()


def test_real_runtime_stdio_without_network_or_writes(tmp_path, sample_ref):
    import hashlib
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from endnote_mcp.db import connect, upsert_reference

    database = tmp_path / 'library.db'
    conn = connect(database)
    ref = dict(sample_ref)
    ref['authors'] = json.dumps(ref['authors'])
    ref['keywords'] = json.dumps(ref['keywords'])
    upsert_reference(conn, ref)
    conn.commit()
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.execute('PRAGMA journal_mode=DELETE')
    conn.close()
    xml = tmp_path / 'library.xml'
    xml.write_text('<xml><records/></xml>')
    config = tmp_path / 'config.yaml'
    config.write_text(f'endnote_xml: {xml}\npdf_dir: {tmp_path}\ndb_path: {database}\n')
    runner = tmp_path / 'readonly_server.py'
    runner.write_text('''import socket, sqlite3, sys
_original_socket = socket.socket
class NoNetworkSocket(_original_socket):
    def connect(self, *a, **kw): raise AssertionError("Network access attempted")
    def bind(self, *a, **kw): raise AssertionError("Listening socket attempted")
socket.socket = NoNetworkSocket
_original_connect = sqlite3.connect
def readonly_connect(database, *a, **kw):
    assert "mode=ro" in str(database), "Writable database connection attempted"
    return _original_connect(database, *a, **kw)
sqlite3.connect = readonly_connect
from endnote_mcp.desktop_server import main
main(sys.argv[1])
''')
    def snapshot():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir() if p.is_file()}
    before = snapshot()

    async def run():
        params = StdioServerParameters(command=sys.executable, args=[str(runner), str(config)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), timeout=30)
                for name, args in [
                    ('search_references', {'query': 'shipping'}),
                    ('search_fulltext', {'query': 'shipping'}),
                    ('search_library', {'query': 'shipping'}),
                    ('get_reference_details', {'rec_number': 42}),
                    ('get_citation', {'rec_number': 42}),
                    ('get_bibliography', {'rec_numbers': '42'}),
                    ('get_bibtex', {'rec_numbers': '42'}),
                    ('read_pdf_section', {'rec_number': 42}),
                    ('list_references_by_topic', {'topic': 'shipping'}),
                    ('find_related', {'rec_number': 42}),
                    ('search_semantic', {'query': 'shipping'}),
                ]:
                    result = await asyncio.wait_for(session.call_tool(name, args), timeout=30)
                    assert not result.isError, (name, result)
                    assert isinstance(result.structuredContent, dict)
    asyncio.run(run())
    asyncio.run(run())
    assert snapshot() == before
