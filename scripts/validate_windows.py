"""Local packaged-runtime acceptance; reports counts, never library passages.

Use a separate output directory: configuration and derived index are private.
This checks native stdio, not the Codex GUI onboarding gate.
"""
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


async def validate(args):
    from endnote_mcp import db
    if os.name != 'nt':
        raise RuntimeError('Run native Windows acceptance on Windows.')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = output / 'config.yaml'
    database = output / 'library.db'
    if config.exists():
        raise RuntimeError('Choose a new acceptance output directory; existing configuration is preserved.')
    hashes = {'xml': digest(args.xml)}
    def cli(*arguments):
        result = subprocess.run([str(args.runtime), *arguments], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(f'Acceptance CLI {arguments[0]} failed; inspect locally (exit {result.returncode}).')
        return result.stdout
    cli('setup', '--xml', str(args.xml), '--pdf-dir', str(args.pdf_dir), '--config', str(config))
    await asyncio.to_thread(cli, 'index', '--config', str(config))
    report = json.loads(cli('status', '--config', str(config)))
    with closing(db.connect_readonly(database)) as connection:
        row = connection.execute('SELECT r.rec_number,r.title,a.attachment_id,a.resolved_path,p.page_number,p.text_content FROM references_ r JOIN attachments a USING(rec_number) JOIN pdf_pages p USING(attachment_id) WHERE a.status="indexed" LIMIT 1').fetchone()
        if row is None:
            raise RuntimeError('Acceptance requires at least one PDF with extracted text.')
        selected = dict(row)
    pdf = Path(selected['resolved_path'])
    hashes['selected_pdf'] = digest(pdf)
    words = re.findall(r'\w+', selected['title'])
    metadata_query = ' '.join(words[:6])
    text_words = re.findall(r'\w+', selected['text_content'])
    pdf_query = max(text_words, key=len)
    manifest = json.loads((args.plugin / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['endnote']
    if manifest['command'] != 'cmd.exe':
        raise RuntimeError('Use the extracted Windows ZIP.')
    params = StdioServerParameters(command=manifest['command'], args=manifest['args'],
        cwd=str(args.plugin.resolve()), env={**os.environ,
            'CHATGPT_ENDNOTE_MCP_COMMAND': str(args.runtime.resolve()),
            'CHATGPT_ENDNOTE_MCP_CONFIG': str(config), 'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1'})
    checked = []
    for restart in range(2):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), 30)
                assert len((await session.list_tools()).tools) == 11
                before = digest(database)
                cases = [('search_references', {'query': metadata_query}),
                    ('search_fulltext', {'query': pdf_query}),
                    ('get_reference_details', {'rec_number': selected['rec_number']}),
                    ('get_citation', {'rec_number': selected['rec_number']}),
                    ('get_bibliography', {'rec_numbers': str(selected['rec_number'])}),
                    ('get_bibtex', {'rec_numbers': str(selected['rec_number'])}),
                    ('read_pdf_section', {'rec_number': selected['rec_number'],
                        'attachment_id': selected['attachment_id'],
                        'start_page': selected['page_number'], 'end_page': selected['page_number']})]
                for tool, arguments in cases:
                    result = await asyncio.wait_for(session.call_tool(tool, arguments), 180)
                    assert not result.isError, tool
                    assert result.structuredContent.get('items'), tool
                    checked.append(tool)
                assert digest(database) == before
                if restart == 0:
                    # A running server reconnects to the newly published database.
                    await asyncio.to_thread(cli, 'index', '--config', str(config))
                    result = await session.call_tool('get_citation', {'rec_number': selected['rec_number']})
                    assert result.structuredContent['items']
    assert digest(args.xml) == hashes['xml']
    assert digest(pdf) == hashes['selected_pdf']
    ready = json.loads(cli('doctor', '--config', str(config)))['ready']
    report.update(ready=ready, tools_registered=11, successful_calls=len(checked),
                  server_restart=True, live_reindex=True, retrieval_preserved_index=True,
                  xml_and_selected_pdf_unchanged=True, gui_onboarding_verified=False)
    (output / 'acceptance-summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--xml', type=Path, required=True)
    parser.add_argument('--pdf-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    asyncio.run(validate(parser.parse_args()))
