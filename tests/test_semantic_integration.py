"""Opt-in integration with actual semantic dependencies and cached model."""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import yaml

pytestmark = pytest.mark.skipif(os.environ.get('ENDNOTE_TEST_SEMANTIC') != '1', reason='Set ENDNOTE_TEST_SEMANTIC=1 to download/test the real model')


def test_real_semantic_offline_and_refresh_with_reader(tmp_path):
    from endnote_mcp import db, embeddings
    from endnote_mcp.desktop_cli import _embed
    from endnote_mcp.indexing import index_library
    from endnote_mcp.config import Config
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    pdfs = tmp_path / 'PDF'
    pdfs.mkdir()
    xml = tmp_path / 'export.xml'
    xml.write_text('<xml><records><record><rec-number>1</rec-number><titles><title>Mitochondrial electron transport and respiration</title></titles><abstract>Energy production in mitochondria</abstract></record></records></xml>', encoding='utf-8')
    database = tmp_path / 'library.db'
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'endnote_xml': str(xml), 'pdf_dir': str(pdfs), 'db_path': str(database)}), encoding='utf-8')
    index_library(Config.load(config))
    assert embeddings.is_available()
    _embed(config)
    with closing(db.connect_readonly(database)) as connection:
        assert db.get_stats(connection)['references_with_embeddings'] == 1
    async def run():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'endnote_mcp.desktop_cli', 'serve-desktop', '--config', str(config)], env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if os.environ.get('ENDNOTE_TEST_PLUGIN'):
            plugin = Path(os.environ['ENDNOTE_TEST_PLUGIN']).resolve()
            server = json.loads((plugin / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['endnote']
            params = StdioServerParameters(command=server['command'], args=server['args'], cwd=str(plugin), env={**os.environ, 'CHATGPT_ENDNOTE_MCP_CONFIG': str(config), 'CHATGPT_ENDNOTE_MCP_COMMAND': os.environ['ENDNOTE_TEST_RUNTIME'], 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), 60)
                before = hashlib.sha256(database.read_bytes()).digest()
                response = await asyncio.wait_for(session.call_tool('search_semantic', {'query': 'cellular energy'}), 120)
                assert not response.isError
                assert response.structuredContent['items'][0]['reference_id'] == 1
                assert hashlib.sha256(database.read_bytes()).digest() == before
                ready, release = tmp_path / 'reader-ready', tmp_path / 'reader-release'
                code = "from endnote_mcp.db import connect_readonly; from pathlib import Path; import sys,time\nc=connect_readonly(sys.argv[1]); Path(sys.argv[2]).touch()\nwhile not Path(sys.argv[3]).exists(): time.sleep(.02)\nc.close()"
                child = subprocess.Popen([sys.executable, '-c', code, str(database), str(ready), str(release)])
                refresh = None
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists():
                        assert child.poll() is None
                        assert time.monotonic() < deadline
                        await asyncio.sleep(.02)
                    refresh = asyncio.create_task(asyncio.to_thread(_embed, config, True))
                    await asyncio.sleep(.25)
                    if os.name == 'nt':
                        assert not refresh.done()
                    release.touch()
                    await asyncio.wait_for(refresh, 120)
                    child.wait(timeout=10)
                    assert child.returncode == 0
                    response = await session.call_tool('search_semantic', {'query': 'respiration'})
                    assert response.structuredContent['items']
                finally:
                    release.touch()
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                    if refresh is not None:
                        await refresh
    asyncio.run(run())
